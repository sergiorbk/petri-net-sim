import type { ChatMessage, ChatSession } from "@/types/chat";

export interface NetVersion {
  versionIndex: number;
  messageId: string;
  snapshotId?: string;
  netSnapshot?: ChatMessage["netSnapshot"];
  label: string;
  createdAt: number;
}

/**
 * Derive the ordered list of net versions for a chat session.
 * Versions are 1-based and correspond to assistant messages that produced a snapshot.
 */
export function getVersionList(session: ChatSession | undefined): NetVersion[] {
  if (!session) return [];

  const versions: NetVersion[] = [];
  let versionIndex = 0;

  for (let i = 0; i < session.messages.length; i++) {
    const msg = session.messages[i];
    const hasSnapshot = Boolean(msg.snapshotId) || Boolean(msg.netSnapshot);
    if (!hasSnapshot) continue;

    versionIndex += 1;

    const promptMsg = findPrecedingUserMessage(session.messages, i);
    const label = promptMsg
      ? truncate(promptMsg.content, 80)
      : (msg.netSnapshot?.name ?? `Version ${versionIndex}`);

    versions.push({
      versionIndex,
      messageId: msg.id,
      snapshotId: msg.snapshotId,
      netSnapshot: msg.netSnapshot,
      label,
      createdAt: msg.timestamp,
    });
  }

  return versions;
}

function findPrecedingUserMessage(
  messages: ChatMessage[],
  fromIndex: number,
): ChatMessage | undefined {
  for (let i = fromIndex - 1; i >= 0; i--) {
    if (messages[i].role === "user") return messages[i];
  }
  return undefined;
}

function truncate(s: string, n: number): string {
  const trimmed = s.trim();
  return trimmed.length > n ? `${trimmed.slice(0, n - 1).trimEnd()}…` : trimmed;
}
