import React from "react";
import { Message } from "../types/chat";
import Markdown from "./Markdown";
import { Logo } from "./forge";

interface Props {
  message: Message;
  turn?: number;
}

const MessageBubble: React.FC<Props> = ({ message }) => {
  if (message.role === "user") {
    return (
      <div className="fade-in flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-iron px-4 py-3 text-[16px] leading-relaxed text-bone whitespace-pre-wrap">
          {message.content}
        </div>
      </div>
    );
  }

  const waiting = message.streaming && !message.content;

  return (
    <div className="fade-in flex gap-3">
      <div className="shrink-0 mt-0.5">
        <Logo size={28} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-bone mb-1.5">SmartSmith</div>
        {waiting ? (
          <div className="max-w-[180px] py-2">
            <div className="heat-bar" />
            <div className="mt-2 text-sm text-smoke">Thinking…</div>
          </div>
        ) : (
          <div className="text-[16px] leading-[1.7] text-bone/95">
            <Markdown text={message.content} />
            {message.streaming && <span className="cursor-blink" />}
          </div>
        )}

        {!message.streaming && (message.agentMode || message.sourceMode) && (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.agentMode && <Tag>{message.agentMode === "multi" ? "Multi-agent" : "Single agent"}</Tag>}
            {message.sourceMode && <Tag>{sourceLabel(message.sourceMode)}</Tag>}
          </div>
        )}
      </div>
    </div>
  );
};

function sourceLabel(mode: string): string {
  if (mode === "vector_only") return "Knowledge base";
  if (mode === "google_only") return "Web search";
  return "Knowledge base + web";
}

const Tag: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="text-xs px-2.5 py-1 rounded-full bg-iron text-ash">{children}</span>
);

export default MessageBubble;
