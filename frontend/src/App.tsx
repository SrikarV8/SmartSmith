import React, { useMemo, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import ChatView from "./components/ChatView";
import CitationsPanel from "./components/CitationsPanel";
import {
  AgentMode,
  Conversation,
  ConversationHistoryItem,
  Message,
} from "./types/chat";
import { sendChatMessage } from "./api/chatApi";
import { useLocalStorage } from "./hooks/useLocalStorage";

const uid = () =>
  Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

const DEFAULT_AGENT_MODE: AgentMode = "single";

const normalizeAgentMode = (mode?: AgentMode): AgentMode =>
  mode === "multi" ? "multi" : DEFAULT_AGENT_MODE;

const toConversationHistory = (
  messages: Message[]
): ConversationHistoryItem[] =>
  messages
    .filter((message) => message.content.trim())
    .map((message) => ({
      role: message.role,
      content: message.content,
    }));

const App: React.FC = () => {
  const [conversations, setConversations] = useLocalStorage<Conversation[]>(
    "smartsmith.conversations",
    []
  );
  const [activeId, setActiveId] = useLocalStorage<string | null>(
    "smartsmith.activeId",
    null
  );
  const [selectedAgentMode, setSelectedAgentMode] =
    useLocalStorage<AgentMode>("smartsmith.agentMode", DEFAULT_AGENT_MODE);
  const [sidebarCollapsed, setSidebarCollapsed] = useLocalStorage<boolean>(
    "smartsmith.sidebarCollapsed",
    false
  );
  const [citationsOpen, setCitationsOpen] = useLocalStorage<boolean>(
    "smartsmith.citationsOpen",
    true
  );
  const [activeCitationMessageId, setActiveCitationMessageId] = useState<
    string | null
  >(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeId) ?? null,
    [conversations, activeId]
  );

  const activeAgentMode = normalizeAgentMode(
    activeConversation?.agentMode ?? selectedAgentMode
  );

  const activeCitationMessage = useMemo(() => {
    if (!activeConversation) return null;
    if (activeCitationMessageId) {
      return (
        activeConversation.messages.find(
          (message) => message.id === activeCitationMessageId
        ) ?? null
      );
    }

    for (let index = activeConversation.messages.length - 1; index >= 0; index--) {
      const message = activeConversation.messages[index];
      if (
        message.role === "assistant" &&
        message.citations &&
        message.citations.length > 0
      ) {
        return message;
      }
    }
    return null;
  }, [activeConversation, activeCitationMessageId]);

  const updateConversation = (
    id: string,
    updater: (conversation: Conversation) => Conversation
  ) => {
    setConversations((prev) =>
      prev.map((conversation) =>
        conversation.id === id ? updater(conversation) : conversation
      )
    );
  };

  const handleNewChat = () => {
    const conversation: Conversation = {
      id: uid(),
      title: "New chat",
      createdAt: Date.now(),
      updatedAt: Date.now(),
      agentMode: activeAgentMode,
      messages: [],
    };
    setConversations((prev) => [conversation, ...prev]);
    setActiveId(conversation.id);
    setActiveCitationMessageId(null);
  };

  const handleSelect = (id: string) => {
    const conversation = conversations.find((item) => item.id === id);
    setActiveId(id);
    setActiveCitationMessageId(null);
    setSelectedAgentMode(normalizeAgentMode(conversation?.agentMode));
  };

  const handleDelete = (id: string) => {
    setConversations((prev) => prev.filter((conversation) => conversation.id !== id));
    if (activeId === id) setActiveId(null);
  };

  const handleAgentModeChange = (mode: AgentMode) => {
    setSelectedAgentMode(mode);
    if (activeConversation) {
      updateConversation(activeConversation.id, (conversation) => ({
        ...conversation,
        agentMode: mode,
        updatedAt: Date.now(),
      }));
    }
  };

  const handleSend = async (text: string) => {
    if (isStreaming) return;

    const agentModeForRequest = activeAgentMode;
    let conversation = activeConversation;
    let conversationId = conversation?.id ?? null;

    if (!conversationId || !conversation) {
      conversation = {
        id: uid(),
        title: text.slice(0, 40),
        createdAt: Date.now(),
        updatedAt: Date.now(),
        agentMode: agentModeForRequest,
        messages: [],
      };
      setConversations((prev) => [conversation!, ...prev]);
      setActiveId(conversation.id);
      conversationId = conversation.id;
    }

    const historyForRequest = toConversationHistory(conversation.messages);

    const userMessage: Message = {
      id: uid(),
      role: "user",
      content: text,
      createdAt: Date.now(),
    };
    const assistantMessage: Message = {
      id: uid(),
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      agentMode: agentModeForRequest,
      streaming: true,
    };

    updateConversation(conversationId, (current) => ({
      ...current,
      title: current.messages.length === 0 ? text.slice(0, 40) : current.title,
      agentMode: agentModeForRequest,
      messages: [...current.messages, userMessage, assistantMessage],
      updatedAt: Date.now(),
    }));

    setIsStreaming(true);
    setActiveCitationMessageId(assistantMessage.id);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await sendChatMessage(
        text,
        agentModeForRequest,
        historyForRequest,
        (token) => {
          updateConversation(conversationId!, (current) => ({
            ...current,
            messages: current.messages.map((message) =>
              message.id === assistantMessage.id
                ? { ...message, content: message.content + token }
                : message
            ),
          }));
        },
        controller.signal
      );

      updateConversation(conversationId, (current) => ({
        ...current,
        agentMode: response.agentMode,
        updatedAt: Date.now(),
        messages: current.messages.map((message) =>
          message.id === assistantMessage.id
            ? {
                ...message,
                content: response.answer,
                streaming: false,
                agentMode: response.agentMode,
                sourceMode: response.sourceMode,
                citations: response.citations,
              }
            : message
        ),
      }));
      setSelectedAgentMode(response.agentMode);
    } catch (err) {
      const isAbort =
        (err as any)?.name === "AbortError" ||
        String(err).toLowerCase().includes("abort");
      const errorText = isAbort
        ? "_[generation stopped]_"
        : `_[error] ${(err as Error)?.message || String(err)}_\n\nMake sure the SmartSmith FastAPI backend is running at ${
            process.env.REACT_APP_API_URL || "http://localhost:8000"
          } (\`uvicorn server:app --reload --port 8000\`).`;

      // eslint-disable-next-line no-console
      console.error("SmartSmith chat error:", err);

      updateConversation(conversationId, (current) => ({
        ...current,
        messages: current.messages.map((message) =>
          message.id === assistantMessage.id
            ? {
                ...message,
                streaming: false,
                content:
                  message.content + (message.content ? "\n\n" : "") + errorText,
              }
            : message
        ),
      }));
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  const handleOpenCitations = (messageId: string) => {
    setActiveCitationMessageId(messageId);
    setCitationsOpen(true);
  };

  return (
    <div className="grain furnace h-screen w-screen flex text-bone overflow-hidden">
      <Sidebar
        conversations={conversations}
        activeId={activeId}
        selectedAgentMode={activeAgentMode}
        onAgentModeChange={handleAgentModeChange}
        onSelect={handleSelect}
        onNewChat={handleNewChat}
        onDelete={handleDelete}
        onSend={handleSend}
        isStreaming={isStreaming}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
      />

      <ChatView
        conversation={activeConversation}
        agentMode={activeAgentMode}
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        onOpenCitations={handleOpenCitations}
        activeCitationMessageId={activeCitationMessageId}
        citationsPanelOpen={citationsOpen}
        onToggleCitationsPanel={() => setCitationsOpen((value) => !value)}
      />

      <CitationsPanel
        message={activeCitationMessage}
        open={citationsOpen}
        onClose={() => setCitationsOpen(false)}
      />
    </div>
  );
};

export default App;
