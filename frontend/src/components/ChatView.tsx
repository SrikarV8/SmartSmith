import React, { useEffect, useRef } from "react";
import { AgentMode, Conversation } from "../types/chat";
import MessageBubble from "./MessageBubble";
import ChatInput from "./ChatInput";
import { STAGES } from "./forge";

interface Props {
  conversation: Conversation | null;
  agentMode: AgentMode;
  onSend: (text: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  onOpenCitations: (messageId: string) => void;
  activeCitationMessageId: string | null;
  onToggleCitationsPanel: () => void;
  citationsPanelOpen: boolean;
}

const ChatView: React.FC<Props> = ({
  conversation,
  agentMode,
  onSend,
  onStop,
  isStreaming,
  onOpenCitations,
  activeCitationMessageId,
  onToggleCitationsPanel,
  citationsPanelOpen,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = conversation?.messages.length ? el.scrollHeight : 0;
  }, [conversation?.messages]);

  const messages = conversation?.messages ?? [];
  const isEmpty = messages.length === 0;

  return (
    <section className="flex-1 flex flex-col min-w-0">
      <header className="h-14 shrink-0 flex items-center justify-between px-6 border-b border-steel/70">
        <div className="min-w-0 text-[15px] font-medium text-bone truncate">
          {isEmpty ? "New chat" : conversation?.title}
        </div>
        <button
          onClick={onToggleCitationsPanel}
          className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
            citationsPanelOpen
              ? "border-steel bg-iron text-bone"
              : "border-steel text-ash hover:text-bone hover:bg-iron"
          }`}
        >
          {citationsPanelOpen ? "Hide sources" : "Show sources"}
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto thin-scroll">
        {isEmpty ? (
          <Hero onSuggest={onSend} disabled={isStreaming} />
        ) : (
          <div className="max-w-3xl mx-auto px-6 py-8 space-y-8">
            {messages.map((m) => (
              <div key={m.id}>
                <MessageBubble message={m} />
                {m.role === "assistant" && !m.streaming && m.citations && m.citations.length > 0 && (
                  <div className="mt-3 pl-10">
                    <button
                      onClick={() => onOpenCitations(m.id)}
                      className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                        activeCitationMessageId === m.id && citationsPanelOpen
                          ? "border-steel bg-iron text-bone"
                          : "border-steel text-ash hover:text-bone hover:bg-iron"
                      }`}
                    >
                      View {m.citations.length} source{m.citations.length === 1 ? "" : "s"}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      <ChatInput
        onSend={onSend}
        disabled={isStreaming}
        isStreaming={isStreaming}
        onStop={onStop}
        agentMode={agentMode}
      />
    </section>
  );
};

const Hero: React.FC<{ onSuggest: (text: string) => void; disabled: boolean }> = ({ onSuggest, disabled }) => (
  <div className="max-w-3xl mx-auto px-6 pt-16 pb-10">
    <h1 className="text-[40px] min-[1180px]:text-[52px] font-semibold leading-[1.08] tracking-tight text-bone">
      Starting a business?
      <br />
      <span className="text-ember">Let’s figure it out together.</span>
    </h1>
    <p className="mt-5 max-w-xl text-[17px] leading-relaxed text-ash">
      Ask about legal structure, funding, budgets, taxes or finding customers. You’ll get a clear answer
      along with the sources it came from.
    </p>

    <div className="mt-10 text-sm font-medium text-smoke">Not sure where to begin? Pick a step:</div>

    <div className="mt-3 grid grid-cols-1 min-[1180px]:grid-cols-2 gap-3">
      {STAGES.map((s) => (
        <button
          key={s.name}
          disabled={disabled}
          onClick={() => onSuggest(s.prompt)}
          className="text-left p-4 rounded-xl border border-steel bg-coal hover:bg-iron hover:border-smoke transition-colors disabled:opacity-50"
        >
          <div className="flex items-center gap-3">
            <span className="w-7 h-7 shrink-0 rounded-full bg-iron text-ash text-sm font-semibold flex items-center justify-center">
              {s.numeral}
            </span>
            <div>
              <div className="text-[15px] font-semibold text-bone">{s.name}</div>
              <div className="text-sm text-smoke">{s.tagline}</div>
            </div>
          </div>
        </button>
      ))}
    </div>
  </div>
);

export default ChatView;
