import { beforeEach, describe, expect, it, vi } from "vitest";
import { downloadExport, downloadNetworkImage } from "./export-client";
import { fetchWithAuth } from "./api-client";

vi.mock("./api-client", () => ({ fetchWithAuth: vi.fn() }));

describe("export downloads", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:download"), revokeObjectURL: vi.fn() });
  });

  it("downloads authenticated server bytes under the session title", async () => {
    const blob = new Blob(["real archive"], { type: "application/zip" });
    vi.mocked(fetchWithAuth).mockResolvedValue({ ok: true, blob: async () => blob,
      headers: new Headers({ "Content-Disposition": "attachment; filename*=UTF-8''Finite_service-training.zip" }),
    } as Response);
    const link = { click: vi.fn(), href: "", download: "" };
    vi.spyOn(document, "createElement").mockReturnValueOnce(link as unknown as HTMLAnchorElement);
    await downloadExport("/api/v1/sessions/id/training-data", { context: { task: "Six tokens" } }, "fallback.zip");
    expect(fetchWithAuth).toHaveBeenCalledWith("/api/v1/sessions/id/training-data", expect.objectContaining({ method: "POST" }));
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
    expect(link.download).toBe("Finite_service-training.zip");
    expect(link.click).toHaveBeenCalledOnce();
  });

  it("sends the supplied editor snapshot to the common image renderer", async () => {
    vi.mocked(fetchWithAuth).mockResolvedValue({ ok: false, status: 400 } as Response);
    const net = { name: "Finite service", places: [], transitions: [], arcs: [] };
    await expect(downloadNetworkImage(net)).rejects.toThrow("400");
    const [, options] = vi.mocked(fetchWithAuth).mock.calls[0];
    expect(JSON.parse(options!.body as string)).toEqual({ net_data: net, title: net.name });
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
