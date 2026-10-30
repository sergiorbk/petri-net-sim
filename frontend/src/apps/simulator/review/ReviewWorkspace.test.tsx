import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReviewWorkspace } from "./ReviewWorkspace";
import { useTrainingStore } from "@/stores/training-store";
import { useEditorStore } from "@/stores/editor-store";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import { exportArchive, type BundleInfo } from "@/lib/training-client";
import i18n from "@/i18n";

vi.mock("./ReviewCanvas", () => ({
    ReviewCanvas: ({
        onFinding,
    }: {
        onFinding: (v: unknown, label: string) => void;
    }) => (
        <button
            onClick={() =>
                onFinding({ element_id: "p1", view_id: "main" }, "Source")
            }
        >
            test canvas element
        </button>
    ),
}));
vi.mock("@/lib/training-client", async (original) => ({
    ...(await original<object>()),
    exportArchive: vi.fn(),
    saveDownload: vi.fn(),
}));

const id = "a".repeat(64);
const second = "b".repeat(64);
const net = {
    name: "Test",
    places: [{ id: "p1", name: "Source", tokens: 1, graphics: { x: 0, y: 0 } }],
    transitions: [],
    arcs: [],
};
const info = {
    manifest: { title: "Review sample" },
    task: { task: "Inspect a token" },
    history: {
        bundle_id: "bundle",
        head_revision_id: second,
        revisions: [
            { id, parent_revision_id: "", model_sha256: "c".repeat(64) },
            {
                id: second,
                parent_revision_id: id,
                model_sha256: "d".repeat(64),
            },
        ],
        reviews: [],
    },
    reviews: [],
    revision_id: second,
    net_data: net,
    warnings: [],
    network_views: { views: [] },
    source_element_map: { p1: "p1" },
    image_sha256: null,
    geometry: { elements: [] },
} satisfies BundleInfo;

beforeEach(async () => {
    await i18n.changeLanguage("en");
    useTrainingStore.setState({
        archive: "saved-zip",
        info: structuredClone(info),
        open: true,
        busy: false,
    });
    useEditorStore.getState().setNet(structuredClone(net));
    useCanvasTabsStore.getState().resetToRoot();
    vi.mocked(exportArchive).mockReset();
});

describe("Portable review workspace", () => {
    it("anchors a finding to the saved version and exports it with the run policy", async () => {
        vi.mocked(exportArchive).mockResolvedValue({
            archive: "next-zip",
            info,
            name: "review.zip",
            blob: new Blob(),
        });
        const before = structuredClone(useEditorStore.getState().net);
        render(<ReviewWorkspace />);
        fireEvent.click(screen.getByText("test canvas element"));
        fireEvent.change(
            screen.getByLabelText("What should be corrected or clarified?"),
            { target: { value: "Explain the token count" } },
        );
        fireEvent.click(
            screen
                .getAllByRole("button", { name: "Add finding" })
                .at(-1)!,
        );
        expect(screen.getByLabelText("Version")).toBeDisabled();
        fireEvent.change(screen.getByLabelText("Review summary"), {
            target: { value: "Needs clarification" },
        });
        fireEvent.click(
            screen.getByRole("button", { name: "Save reviewed ZIP" }),
        );
        await waitFor(() => expect(exportArchive).toHaveBeenCalledOnce());
        expect(vi.mocked(exportArchive).mock.calls[0][0]).toMatchObject({
            archive_base64: "saved-zip",
            net_data: net,
            review: {
                revision_id: second,
                comment: "Needs clarification",
                simulation_horizons: [100, 1000, 10000],
                findings: [
                    {
                        element_id: "p1",
                        view_id: "main",
                        message: "Explain the token count",
                    },
                ],
            },
        });
        expect(useEditorStore.getState().net).toEqual(before);
    });

    it("requires a reason when automatic runs are disabled", () => {
        render(<ReviewWorkspace />);
        fireEvent.change(screen.getByLabelText("Review summary"), {
            target: { value: "Structure only" },
        });
        fireEvent.click(
            screen.getByRole("button", { name: "Simulation" }),
        );
        fireEvent.click(
            screen.getByLabelText("Run automatically before saving"),
        );
        expect(
            screen.getByRole("button", { name: "Save reviewed ZIP" }),
        ).toBeDisabled();
        fireEvent.change(
            screen.getByLabelText("Reason for skipping automatic simulation"),
            { target: { value: "This task concerns structure" } },
        );
        expect(
            screen.getByRole("button", { name: "Save reviewed ZIP" }),
        ).not.toBeDisabled();
    });

    it("cancelling a finding adds nothing and keeps version selection available", () => {
        render(<ReviewWorkspace />);
        fireEvent.click(screen.getByText("test canvas element"));
        fireEvent.change(
            screen.getByLabelText("What should be corrected or clarified?"),
            { target: { value: "Unsaved" } },
        );
        fireEvent.click(
            screen.getByRole("button", { name: "Cancel" }),
        );
        expect(screen.getByLabelText("Version")).not.toBeDisabled();
        expect(screen.queryByText("Unsaved")).not.toBeInTheDocument();
    });
});
