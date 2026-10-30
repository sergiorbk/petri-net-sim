import { create } from "zustand";
import i18n from "@/i18n";
import { useEditorStore } from "./editor-store";
import { useCanvasTabsStore } from "./canvas-tabs-store";
import {
    inspectArchive,
    blobBase64,
    exportArchive,
    saveDownload,
    type BundleInfo,
} from "@/lib/training-client";

interface TrainingState {
    archive: string | null;
    info: BundleInfo | null;
    open: boolean;
    busy: boolean;
    reviewDirty: boolean;
    show: () => void;
    close: () => void;
    clear: () => void;
    adopt: (archive: string, info: BundleInfo) => void;
}

export const useTrainingStore = create<TrainingState>((set) => ({
    archive: null,
    info: null,
    open: false,
    busy: false,
    reviewDirty: false,
    show: () => set({ open: true }),
    close: () => set({ open: false, reviewDirty: false }),
    clear: () =>
        set({ archive: null, info: null, open: false, reviewDirty: false }),
    adopt: (archive, info) => set({ archive, info }),
}));

export async function openTrainingFile(file: File): Promise<void> {
    const editor = useEditorStore.getState();
    if (
        (editor.dirty || useTrainingStore.getState().reviewDirty) &&
        !window.confirm(i18n.t("review.replaceCurrent"))
    )
        return;
    if (file.size > 256 * 1024 * 1024) throw new Error("Archive too large");
    const archive = await blobBase64(file);
    const info = await inspectArchive(archive);
    // Validate before replacing the document or its portable history.
    useCanvasTabsStore.getState().resetToRoot();
    editor.setNet(info.net_data);
    useEditorStore.setState({ cloudNetId: null });
    useTrainingStore.setState({ archive, info, open: true });
}

export function pickTrainingFile(): void {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".zip";
    input.onchange = () => {
        const file = input.files?.[0];
        if (file)
            void openTrainingFile(file).catch(async () => {
                const { toast } = await import("./toast-store");
                toast(i18n.t("review.invalidArchive"), "error");
            });
    };
    input.click();
}

export async function exportTrainingData(task?: string): Promise<void> {
    const state = useTrainingStore.getState();
    if (state.busy) return;
    useTrainingStore.setState({ busy: true });
    try {
        const tabs = useCanvasTabsStore.getState();
        if (tabs.activeId !== "main")
            throw new Error(i18n.t("review.useMainCanvas"));
        const net = useEditorStore.getState().net;
        const result = await exportArchive({
            net_data: net,
            title: net.name,
            archive_base64: state.archive,
            context: task === undefined ? {} : { task: task || null },
        });
        useTrainingStore.getState().adopt(result.archive, result.info);
        saveDownload(result.blob, result.name);
    } finally {
        useTrainingStore.setState({ busy: false });
    }
}
