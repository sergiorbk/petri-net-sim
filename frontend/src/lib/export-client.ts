import { fetchWithAuth } from "@/lib/api-client";
import type { PetriNetData } from "@/types/petri";

export async function downloadExport(path: string, body: unknown, fallback: string): Promise<void> {
  const response = await fetchWithAuth(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Export failed (${response.status})`);
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const name = encoded ? decodeURIComponent(encoded) : fallback;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadNetworkImage(net: PetriNetData): Promise<void> {
  return downloadExport("/api/v1/sessions/exports/image", { net_data: net, title: net.name }, "network.png");
}
