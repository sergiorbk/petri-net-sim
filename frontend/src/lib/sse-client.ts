import { getStoredTokens } from "@/lib/api-client";

export interface AgentEventPayload {
  type: "tool_call" | "tool_result";
  id: string;
  name?: string | null;
  input?: Record<string, unknown> | null;
  status?: "running" | "success" | "error" | null;
  output?: string | null;
}

export interface ChatCompletionDelta {
  role?: string | null;
  content?: string | null;
  agent_event?: AgentEventPayload | null;
}

export interface ChatCompletionChunk {
  id: string;
  /** Petri Net Sim extension: backend SHA-256 session fingerprint */
  session_id?: string | null;
  /** Petri Net Sim extension: UUID of the net snapshot saved for this turn */
  snapshot_id?: string | null;
  choices: Array<{
    index: number;
    delta: ChatCompletionDelta;
    finish_reason: string | null;
  }>;
}

export interface StreamCallbacks {
  onChunk: (chunk: ChatCompletionChunk) => void;
  onDone: () => void;
  onError: (error: string) => void;
}

interface ChatMessage {
  role: string;
  content: string | null;
}

/**
 * metadata.agent_effort value meaning "do not cap this turn". The backend
 * resolves it to a ceiling high enough that no real build reaches it
 * (AGENT_RECURSION_LIMIT_UNCAPPED), which is a runaway backstop rather
 * than a budget. The workbench always sends this: a turn that stops at
 * step 100 leaves a half-built net behind. "standard"/"thorough" stay
 * supported for any other OpenAI-compatible client that asks for them.
 */
export const UNCAPPED_AGENT_EFFORT = "uncapped";

interface CompletionRequest {
  model: string;
  messages: ChatMessage[];
  stream: boolean;
  metadata?: {
    llm_credential_id?: string;
    net_style?: string;
    agent_effort?: string;
    layout_direction?: string;
  };
}

export interface StreamOptions {
  credentialId?: string | null;
  /** Petri Net Sim extension: which net shape the agent should build this
   * turn ("classical" | "object") — see chat_node.py's DEFAULT_NET_STYLE. */
  netStyle?: string;
  /** Petri Net Sim extension: agent tool-call budget for this turn
   * ("standard" | "thorough" | "uncapped") — see chat.py's
   * _resolve_recursion_limit. */
  agentEffort?: string;
  /** Petri Net Sim extension: which way the net this turn builds should
   * flow ("LR" | "TB") — applied to the builder, never to the LLM, so
   * positions stay computed by the layout engine. See chat.py's
   * _resolve_layout_direction. */
  layoutDirection?: string;
  signal?: AbortSignal;
}

export async function streamChatCompletion(
  messages: ChatMessage[],
  callbacks: StreamCallbacks,
  options?: StreamOptions,
): Promise<void> {
  const tokens = getStoredTokens();

  const metadata: CompletionRequest["metadata"] = {
    ...(options?.credentialId ? { llm_credential_id: options.credentialId } : {}),
    ...(options?.netStyle ? { net_style: options.netStyle } : {}),
    ...(options?.agentEffort ? { agent_effort: options.agentEffort } : {}),
    ...(options?.layoutDirection ? { layout_direction: options.layoutDirection } : {}),
  };

  const body: CompletionRequest = {
    model: "petri-net-sim",
    messages,
    stream: true,
    ...(Object.keys(metadata).length > 0 ? { metadata } : {}),
  };

  let response: Response;
  try {
    response = await fetch("/api/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(tokens?.access_token
          ? { Authorization: `Bearer ${tokens.access_token}` }
          : {}),
      },
      body: JSON.stringify(body),
      signal: options?.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      callbacks.onDone();
      return;
    }
    callbacks.onError("Network error");
    return;
  }

  if (!response.ok) {
    let errorMsg = "Request failed";
    try {
      const json = await response.json();
      errorMsg = json.error?.message ?? json.detail ?? errorMsg;
    } catch {
      // ignore parse error
    }
    callbacks.onError(errorMsg);
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    callbacks.onError("No response body");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");

      // Keep the last potentially incomplete line in the buffer
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith(":")) continue;

        if (trimmed === "data: [DONE]") {
          callbacks.onDone();
          return;
        }

        if (trimmed.startsWith("data: ")) {
          const jsonStr = trimmed.slice(6);
          try {
            const chunk = JSON.parse(jsonStr) as ChatCompletionChunk;
            callbacks.onChunk(chunk);
          } catch {
            // Skip malformed chunks
          }
        }
      }
    }

    // Process any remaining buffer
    if (buffer.trim() === "data: [DONE]") {
      callbacks.onDone();
    }
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      callbacks.onDone();
      return;
    }
    throw err;
  } finally {
    reader.releaseLock();
  }

  callbacks.onDone();
}
