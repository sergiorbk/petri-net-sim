import { apiClient, publicApiClient } from "@/lib/api-client";
import type { ObjectFrame, ObjectLink, PetriArc, PetriPlace, PetriTransition } from "@/types/petri";

export interface PetriObjectInterface {
  input_place_id: string | null;
  output_place_id: string | null;
}

export interface PetriObjectTemplate {
  name: string;
  places: PetriPlace[];
  transitions: PetriTransition[];
  arcs: PetriArc[];
  interface: PetriObjectInterface;
  /**
   * Nested frames and internal object links of a composed template; absent
   * on flat templates and on entries saved before nesting was captured.
   */
  objects?: ObjectFrame[];
  links?: ObjectLink[];
}

export interface PetriObjectSummary {
  id: string;
  name: string;
  description: string | null;
  is_builtin: boolean;
  updated_at: string;
}

export interface PetriObjectDetail extends PetriObjectSummary {
  template_data: PetriObjectTemplate;
  preview_svg: string | null;
  created_at: string;
}

export interface PetriObjectCreateRequest {
  name: string;
  description?: string | null;
  template_data: PetriObjectTemplate;
  preview_svg?: string | null;
}

export interface PetriObjectUpdateRequest {
  name?: string;
  description?: string | null;
  template_data?: PetriObjectTemplate;
  preview_svg?: string | null;
}

/**
 * GET /petri-objects is readable by anonymous users (built-ins only).
 * We use apiClient to attach the auth header when available so the user
 * also gets their own custom objects; if no token is present, apiClient
 * still succeeds (the backend treats the request as anonymous).
 */
export function listPetriObjects(options: { anonymous?: boolean } = {}) {
  const client = options.anonymous ? publicApiClient : apiClient;
  return client<PetriObjectSummary[]>("/api/v1/petri-objects");
}

export function getPetriObject(id: string, options: { anonymous?: boolean } = {}) {
  const client = options.anonymous ? publicApiClient : apiClient;
  return client<PetriObjectDetail>(
    `/api/v1/petri-objects/${encodeURIComponent(id)}`,
  );
}

export function createPetriObject(body: PetriObjectCreateRequest) {
  return apiClient<PetriObjectDetail>("/api/v1/petri-objects", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function updatePetriObject(id: string, body: PetriObjectUpdateRequest) {
  return apiClient<PetriObjectDetail>(
    `/api/v1/petri-objects/${encodeURIComponent(id)}`,
    {
      method: "PUT",
      body: JSON.stringify(body),
    },
  );
}

export function deletePetriObject(id: string) {
  return apiClient<{ deleted: boolean }>(
    `/api/v1/petri-objects/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  );
}
