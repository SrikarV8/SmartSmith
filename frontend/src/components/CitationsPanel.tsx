import React from "react";
import { Citation, Message } from "../types/chat";

interface Props {
  message: Message | null;
  open: boolean;
  onClose: () => void;
}

const CitationsPanel: React.FC<Props> = ({ message, open, onClose }) => {
  if (!open) return null;

  const citations = message?.citations ?? [];

  return (
    <aside className="hidden min-[1100px]:flex w-[340px] shrink-0 border-l border-steel/70 bg-coal/90 flex flex-col">
      <div className="h-14 flex items-center justify-between px-5 border-b border-steel/70">
        <div>
          <div className="text-[15px] font-semibold text-bone leading-none">Sources</div>
          <div className="text-xs text-smoke mt-1">
            {assayLine(message)}
          </div>
        </div>
        <button
          onClick={onClose}
          title="Close"
          className="w-8 h-8 rounded-lg text-ash hover:text-bone hover:bg-iron flex items-center justify-center"
        >
          ✕
        </button>
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll px-4 py-4 space-y-3">
        {citations.length === 0 && (
          <div className="text-[13px] leading-relaxed text-smoke px-1 py-2">
            No sources yet. Once you ask a question, the guides and web pages used for the answer will be listed here.
          </div>
        )}
        {citations.map((c, idx) => (
          <CitationCard key={idx} citation={c} index={idx + 1} />
        ))}
      </div>
    </aside>
  );
};

const CitationCard: React.FC<{ citation: Citation; index: number }> = ({ citation, index }) => {
  const isVector = citation.source === "vector";
  return (
    <a
      href={citation.url}
      target="_blank"
      rel="noreferrer"
      className="block p-3.5 rounded-xl bg-ink border border-steel hover:border-smoke transition-colors"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-ember-soft">
          {index}. {isVector ? "Knowledge base" : "Web"}
        </span>
        {citation.score !== undefined && (
          <span className="text-xs text-smoke">{Math.round(citation.score * 100)}% match</span>
        )}
      </div>
      <div className="text-[15px] font-semibold leading-snug text-bone line-clamp-2">
        {citation.title}
      </div>
      {citation.snippet && (
        <div className="mt-1.5 text-[12px] leading-relaxed text-ash line-clamp-3">{citation.snippet}</div>
      )}
      <div className="mt-2 text-xs text-smoke truncate">{citation.url}</div>
    </a>
  );
};

function assayLine(message: Message | null): string {
  if (!message) return "Where this answer came from";
  const mode =
    message.sourceMode === "vector_only"
      ? "Knowledge base"
      : message.sourceMode === "google_only"
      ? "Web search"
      : message.sourceMode === "hybrid"
      ? "Knowledge base + web"
      : "Where this answer came from";
  const crew = message.agentMode === "multi" ? "Multi-agent" : message.agentMode === "single" ? "Single agent" : "";
  return crew ? `${crew} · ${mode}` : mode;
}

export default CitationsPanel;
