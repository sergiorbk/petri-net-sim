import { apiClient } from "@/lib/api-client";
import type { PetriNetData } from "@/types/petri";

/**
 * Fetch a single net snapshot by ID for a given backend session.
 * Used for cold-loading a workbench URL when the snapshot is not in localStorage
 * (incognito, different device, shared link).
 *
 * Endpoint: GET /api/v1/sessions/{sessionId}/snapshots/{snapshotId}
 * Returns 404 if the snapshot belongs to a different session or has been pruned.
 */
export async function fetchSnapshot(
  sessionId: string,
  snapshotId: string,
): Promise<
  | { data: PetriNetData; ok: true }
  | { error: string; status: number; ok: false }
> {
  return apiClient<PetriNetData>(
    `/api/v1/sessions/${sessionId}/snapshots/${snapshotId}`,
  );
}
