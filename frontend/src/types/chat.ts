export type Role = "user" | "assistant";
export type AgentMode = "single" | "multi";

export type SourceMode = "vector_only" | "hybrid" | "google_only";

export interface Citation {
  title: string;
  url: string;
  snippet?: string;
  score?: number;
  source: "vector" | "web";
}

export interface Message {
  id: string;
  role: Role;
  content: string;
  createdAt: number;
  agentMode?: AgentMode;
  sourceMode?: SourceMode;
  citations?: Citation[];
  // While assistant message is streaming
  streaming?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  agentMode?: AgentMode;
  messages: Message[];
}

export interface ConversationHistoryItem {
  role: Role;
  content: string;
}

export interface ChatResponse {
  answer: string;
  agentMode: AgentMode;
  sourceMode: SourceMode;
  citations: Citation[];
}
