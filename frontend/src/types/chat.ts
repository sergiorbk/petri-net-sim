import type { PetriNetData } from "./petri";

export type MessageRole = "user" | "assistant";

export interface AgentToolCall {
  type: "tool_call";
  id: string;
  name: string;
  input: Record<string, unknown>;
  status: "running" | "success" | "error";
}

export interface AgentToolResult {
  type: "tool_result";
  id: string;
  status: "success" | "error";
  output: string;
}

export type AgentStep = AgentToolCall | AgentToolResult;

export type TimelineItem =
  | { kind: "text"; content: string }
  | { kind: "tool_call"; stepId: string };

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  steps?: AgentStep[];
  timeline?: TimelineItem[];
  timestamp: number;
  /**
   * Snapshot of the Petri net at the moment this message's simulation ran.
   * Present only on assistant messages that contain a successful run_simulation call.
   * Kept as a localStorage fallback when the backend DB is unavailable.
   */
  netSnapshot?: PetriNetData;
  /**
   * UUID of the NetSnapshot row in the backend DB for this message's net version.
   * Preferred over netSnapshot.net_data for simulate requests — resolves from DB
   * and survives backend restarts without re-sending the full JSON.
   */
  snapshotId?: string;
}

export type SessionVisibility = "private" | "link_only";

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
  /** Backend SHA-256 session fingerprint, received from the first SSE chunk. */
  backendSessionId?: string;
  /** Stable UUID used to build share URLs. Populated after first backend sync. */
  shareToken?: string;
  /** Access control for the share link. */
  visibility?: SessionVisibility;
  /** True when this session was opened via someone else's share link. */
  isShared?: boolean;
}
