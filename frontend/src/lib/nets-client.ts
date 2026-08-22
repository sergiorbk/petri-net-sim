import { apiClient, publicApiClient } from "@/lib/api-client";
import type { PetriNetData } from "@/types/petri";

export type SortBy = "updated_at" | "created_at";
export type NetVisibility = "private" | "link_only";

export interface ThumbnailNode {
  id: string;
  type: "place" | "transition";
  x: number;
  y: number;
}

export interface ThumbnailArc {
  source_id: string;
  target_id: string;
}

export interface UserNetSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  thumbnail: ThumbnailNode[];
  thumbnail_arcs: ThumbnailArc[];
  share_token?: string;
  visibility?: NetVisibility;
  /** True when this net was added from someone else's share link (localStorage-only). */
  isShared?: boolean;
}

export interface UserNetListPage {
  items: UserNetSummary[];
  has_more: boolean;
}

export interface UserNetDetail extends UserNetSummary {
  net_data: PetriNetData;
  origin_snapshot_id: string | null;
}

export interface SharedNetView extends UserNetDetail {
  share_token: string;
  visibility: NetVisibility;
}

export interface UserNetCreateRequest {
  name: string;
  net_data: PetriNetData;
  origin_snapshot_id?: string | null;
}

export interface UserNetUpdateRequest {
  name?: string;
  net_data?: PetriNetData;
}

export interface ListUserNetsParams {
  limit?: number;
  offset?: number;
  sort_by?: SortBy;
}

export function listUserNets(params: ListUserNetsParams = {}) {
  const q = new URLSearchParams();
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  if (params.offset !== undefined) q.set("offset", String(params.offset));
  if (params.sort_by) q.set("sort_by", params.sort_by);
  const qs = q.toString();
  return apiClient<UserNetListPage>(`/api/v1/nets${qs ? `?${qs}` : ""}`);
}

export function getUserNet(id: string) {
  return apiClient<UserNetDetail>(`/api/v1/nets/${encodeURIComponent(id)}`);
}

export function createUserNet(body: UserNetCreateRequest) {
  return apiClient<UserNetDetail>("/api/v1/nets", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updateUserNet(id: string, body: UserNetUpdateRequest) {
  return apiClient<UserNetDetail>(`/api/v1/nets/${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteUserNet(id: string) {
  return apiClient<{ deleted: boolean }>(
    `/api/v1/nets/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}

export function shareUserNet(id: string, visibility: NetVisibility) {
  return apiClient<{ share_token: string; visibility: string }>(
    `/api/v1/nets/${encodeURIComponent(id)}/share`,
    { method: "PATCH", body: JSON.stringify({ visibility }) },
  );
}

export function getSharedNet(shareToken: string) {
  return publicApiClient<SharedNetView>(
    `/api/v1/nets/shared/${encodeURIComponent(shareToken)}`,
  );
}
