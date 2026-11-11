import React from "react";
import { AgentMode, Conversation } from "../types/chat";
import { Logo, STAGES } from "./forge";

interface SidebarProps {
  conversations: Conversation[];
  activeId: string | null;
  selectedAgentMode: AgentMode;
  onAgentModeChange: (mode: AgentMode) => void;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  onDelete: (id: string) => void;
  onSend: (text: string) => void;
  isStreaming: boolean;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({
  conversations,
  activeId,
  selectedAgentMode,
  onAgentModeChange,
  onSelect,
  onNewChat,
  onDelete,
  onSend,
  isStreaming,
  collapsed,
  onToggleCollapsed,
}) => {
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt);

  if (collapsed) {
    return (
      <aside className="w-[64px] shrink-0 bg-coal border-r border-steel/70 flex flex-col items-center py-4 gap-3">
        <button onClick={onToggleCollapsed} title="Open sidebar">
          <Logo size={30} />
        </button>
        <button
          onClick={onNewChat}
          title="New chat"
          className="mt-2 w-9 h-9 rounded-lg border border-steel text-ash hover:bg-iron hover:text-bone text-lg leading-none"
        >
          +
        </button>
      </aside>
    );
  }

  return (
    <aside className="w-[280px] shrink-0 bg-coal border-r border-steel/70 flex flex-col">
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Logo size={30} />
            <div className="text-[19px] font-semibold text-bone leading-none">SmartSmith</div>
          </div>
          <button
            onClick={onToggleCollapsed}
            title="Collapse sidebar"
            className="w-8 h-8 rounded-lg text-smoke hover:text-bone hover:bg-iron text-lg leading-none"
          >
            ‹
          </button>
        </div>
        <button
          onClick={onNewChat}
          className="mt-4 w-full text-sm font-medium py-2.5 rounded-lg border border-steel text-bone hover:bg-iron transition-colors"
        >
          + New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll px-4">
        <div className="pt-3">
          <div className="text-xs font-medium text-smoke mb-2">Answer mode</div>
          <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-ink">
            <ModeButton
              label="Single agent"
              active={selectedAgentMode === "single"}
              onClick={() => onAgentModeChange("single")}
            />
            <ModeButton
              label="Multi-agent"
              active={selectedAgentMode === "multi"}
              onClick={() => onAgentModeChange("multi")}
            />
          </div>
          <div className="mt-2 text-xs leading-snug text-smoke">
            {selectedAgentMode === "multi"
              ? "Routes your question to a legal, finance, planning or budget specialist."
              : "One assistant searches all the guides and the web."}
          </div>
        </div>

        <div className="pt-6">
          <div className="text-xs font-medium text-smoke mb-1">Getting started</div>
          <ul>
            {STAGES.map((s) => (
              <li key={s.name}>
                <button
                  disabled={isStreaming}
                  onClick={() => onSend(s.prompt)}
                  className="w-full flex items-center gap-2.5 text-left px-2 py-1.5 -mx-2 rounded-lg text-sm text-ash hover:bg-iron hover:text-bone transition-colors disabled:opacity-40"
                >
                  <span className="w-5 text-xs text-smoke">{s.numeral}</span>
                  {s.name}
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="pt-6 pb-3">
          <div className="text-xs font-medium text-smoke mb-1">Recent chats</div>
          {sorted.length === 0 && <div className="text-sm text-smoke py-1">No chats yet.</div>}
          {sorted.map((conversation) => {
            const isActive = conversation.id === activeId;
            return (
              <div
                key={conversation.id}
                onClick={() => onSelect(conversation.id)}
                className={`group flex items-center justify-between gap-2 px-2 py-2 -mx-2 rounded-lg cursor-pointer transition-colors ${
                  isActive ? "bg-iron text-bone" : "text-ash hover:bg-iron/60 hover:text-bone"
                }`}
              >
                <div className="min-w-0">
                  <div className="truncate text-sm">{conversation.title || "New chat"}</div>
                  <div className="text-xs text-smoke">
                    {conversation.agentMode === "multi" ? "Multi-agent" : "Single agent"} ·{" "}
                    {new Date(conversation.updatedAt).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                  </div>
                </div>
                <button
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete(conversation.id);
                  }}
                  title="Delete chat"
                  className="opacity-0 group-hover:opacity-100 text-smoke hover:text-bone transition-opacity text-sm"
                >
                  ✕
                </button>
              </div>
            );
          })}
        </div>
      </div>

      <div className="border-t border-steel/70 px-4 py-3 text-xs text-smoke">Built at Texas BAXA</div>
    </aside>
  );
};

const ModeButton: React.FC<{ label: string; active: boolean; onClick: () => void }> = ({ label, active, onClick }) => (
  <button
    onClick={onClick}
    className={`text-sm py-1.5 rounded-md transition-colors ${
      active ? "bg-iron text-bone font-medium" : "text-smoke hover:text-bone"
    }`}
  >
    {label}
  </button>
);

export default Sidebar;
