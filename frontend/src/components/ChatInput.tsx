import React, { useEffect, useRef, useState } from "react";
import { AgentMode } from "../types/chat";

interface Props {
  onSend: (text: string) => void;
  disabled?: boolean;
  onStop?: () => void;
  isStreaming?: boolean;
  agentMode: AgentMode;
}

const ChatInput: React.FC<Props> = ({ onSend, disabled, onStop, isStreaming }) => {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 180) + "px";
  }, [value]);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="w-full max-w-3xl mx-auto px-6 pb-5">
      <div className="flex items-end gap-2 bg-coal border border-steel rounded-2xl pl-5 pr-2 py-2 focus-within:border-smoke transition-colors">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          rows={1}
          placeholder="Ask about starting or running your business…"
          className="flex-1 bg-transparent resize-none outline-none text-bone placeholder-smoke text-[16px] leading-relaxed py-2 max-h-[180px] thin-scroll"
        />
        {isStreaming ? (
          <button
            onClick={onStop}
            className="shrink-0 text-sm font-medium px-4 py-2 rounded-xl border border-steel text-ash hover:text-bone hover:border-smoke transition-colors"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!value.trim() || disabled}
            className="shrink-0 text-sm font-medium px-4 py-2 rounded-xl bg-bone text-ink hover:bg-white disabled:opacity-30 disabled:cursor-not-allowed transition"
          >
            Send
          </button>
        )}
      </div>
      <div className="text-center text-xs text-smoke mt-2.5">
        SmartSmith gives general guidance, not legal or financial advice. Check the sources before you act.
      </div>
    </div>
  );
};

export default ChatInput;
