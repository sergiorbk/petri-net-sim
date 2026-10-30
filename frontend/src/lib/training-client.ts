import { fetchWithAuth } from "./api-client";
import type { PetriNetData } from "@/types/petri";

export interface Finding {
    severity: "error" | "warning" | "suggestion";
    message: string;
    element_id?: string;
    view_id?: string;
    region?: {
        coordinate_system: "image-pixels";
        image_sha256: string;
        x: number;
        y: number;
        width: number;
        height: number;
    };
}
export interface SimulationRun {
    source: string;
    status: string;
    error: string;
    horizon: number;
    observed_until?: number;
    source_model_sha256: string;
    trajectory: {
        columns: { id: string; name: string; kind: string; metric: string }[];
        samples: number[][];
        effective_interval: number;
        complete: boolean;
    };
}
export interface ReviewRecord {
    reviewer: string;
    reviewer_kind: string;
    decision: string;
    comment: string;
    created_at: string;
    revision_id: string;
    result_revision_id: string;
    findings: Finding[];
    simulation?: {
        automatic_runs: SimulationRun[];
        interactive_runs: SimulationRun[];
        skip_reason: string;
    };
}
export interface BundleInfo {
    manifest: { title: string; contributor?: Record<string, string> };
    task: {
        task?: string | null;
        clarifications?: string[];
        acceptance?: string[];
    };
    history: {
        bundle_id: string;
        head_revision_id: string;
        revisions: {
            id: string;
            parent_revision_id: string;
            model_sha256: string;
        }[];
        reviews: { id: string }[];
    };
    reviews: ReviewRecord[];
    revision_id: string;
    net_data: PetriNetData;
    warnings: { code: string; message: string }[];
    network_views: {
        views: { id: string; name?: string; image: string; geometry: string }[];
    };
    source_element_map: Record<string, string>;
    image_sha256: string | null;
    geometry: {
        transform?: { origin_x: number; origin_y: number; scale: number };
        image?: { width: number; height: number };
        elements: {
            id: string;
            kind: string;
            bounds: { x: number; y: number; width: number; height: number };
        }[];
    };
}
export interface RevisionChange {
    element_id: string;
    name: string;
    kind: string;
    change: string;
    field?: string;
    before?: string;
    after?: string;
}

export function blobBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });
}

export async function trainingRequest<T>(
    operation: string,
    body: unknown,
): Promise<T> {
    const response = await fetchWithAuth(`/api/v1/training/${operation}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(String(response.status));
    return response.json() as Promise<T>;
}

export function inspectArchive(
    archive: string,
    revision?: string,
): Promise<BundleInfo> {
    return trainingRequest("inspect", {
        archive_base64: archive,
        revision_id: revision,
    });
}

export async function exportArchive(
    body: unknown,
): Promise<{ blob: Blob; name: string; archive: string; info: BundleInfo }> {
    const response = await fetchWithAuth("/api/v1/training/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(String(response.status));
    const blob = await response.blob();
    const archive = await blobBase64(blob);
    const info = await inspectArchive(archive);
    const encoded = response.headers
        .get("Content-Disposition")
        ?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
    return {
        blob,
        archive,
        info,
        name: encoded ? decodeURIComponent(encoded) : "training.zip",
    };
}

export function saveDownload(blob: Blob, name: string): void {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
