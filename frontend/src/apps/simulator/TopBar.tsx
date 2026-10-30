import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import {
    useEditorStore,
    EDGE_STYLE_OPTIONS,
    FRAME_STYLE_OPTIONS,
} from "@/stores/editor-store";
import { useAuthStore } from "@/stores/auth-store";
import { useSimulationStore } from "@/stores/simulation-store";
import { usePetriObjectStore } from "@/stores/petri-object-store";
import { extractSelectionAsTemplate } from "@/lib/petri-object-model";
import { toast } from "@/stores/toast-store";
import { useFileActions } from "./hooks/use-file-actions";
import { SaveObjectDialog } from "./dialogs/SaveObjectDialog";
import { useTrainingStore, pickTrainingFile } from "@/stores/training-store";
import { TrainingExportDialog } from "./review/TrainingExportDialog";

interface MenuItem {
    label: string;
    shortcut?: string;
    action: () => void;
    disabled?: boolean;
    separator?: false;
}

interface MenuSeparator {
    separator: true;
}

interface MenuSubmenu {
    label: string;
    submenu: MenuEntry[];
}

type MenuEntry = MenuItem | MenuSeparator | MenuSubmenu;

interface MenuDef {
    label: string;
    items: MenuEntry[];
}

function isSeparator(entry: MenuEntry): entry is MenuSeparator {
    return "separator" in entry && entry.separator === true;
}

function isSubmenu(entry: MenuEntry): entry is MenuSubmenu {
    return "submenu" in entry;
}

export function TopBar() {
    const { t } = useTranslation();
    const netName = useEditorStore((s) => s.net.name);
    const dirty = useEditorStore((s) => s.dirty);
    const pastLen = useEditorStore((s) => s.past.length);
    const futureLen = useEditorStore((s) => s.future.length);
    const selectionLen = useEditorStore((s) => s.selection.length);
    const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

    const {
        handleNew,
        handleSave,
        handleSaveAs,
        openExportDialog,
        exportDialogOpen,
        closeExportDialog,
        ExportDialogComponent,
        handleImport,
    } = useFileActions();

    const undo = useEditorStore((s) => s.undo);
    const redo = useEditorStore((s) => s.redo);
    const copySelection = useEditorStore((s) => s.copySelection);
    const cutSelection = useEditorStore((s) => s.cutSelection);
    const paste = useEditorStore((s) => s.paste);
    const selectAll = useEditorStore((s) => s.selectAll);
    const deleteSelection = useEditorStore((s) => s.deleteSelection);
    const hasClipboard = useEditorStore((s) => s.clipboard !== null);
    const groupSelectionIntoObject = useEditorStore(
        (s) => s.groupSelectionIntoObject,
    );

    const smoothAnimations = useSimulationStore((s) => s.smoothAnimations);
    const toggleSmoothAnimations = useSimulationStore(
        (s) => s.setSmoothAnimations,
    );

    const edgeStyle = useEditorStore((s) => s.edgeStyle);
    const frameStyle = useEditorStore((s) => s.frameStyle);
    const setFrameStyle = useEditorStore((s) => s.setFrameStyle);
    const setEdgeStyle = useEditorStore((s) => s.setEdgeStyle);

    const [saveObjectOpen, setSaveObjectOpen] = useState(false);
    const [trainingExportOpen, setTrainingExportOpen] = useState(false);

    const hasNodeSelection = useEditorStore((s) =>
        s.selection.some((r) => r.kind === "place" || r.kind === "transition"),
    );

    const handleSaveObject = useCallback(
        async (name: string, description: string) => {
            const { net, selection } = useEditorStore.getState();
            const selIds = new Set(selection.map((s) => s.id));
            const template = extractSelectionAsTemplate(net, selIds);
            if (!template) return;

            const created = await usePetriObjectStore.getState().create({
                name,
                description: description || null,
                template_data: { name, ...template },
            });
            if (!created) {
                toast(
                    usePetriObjectStore.getState().error ??
                        t("dialog.saveObject.saveFailed"),
                    "error",
                );
                return;
            }
            setSaveObjectOpen(false);
        },
        [t],
    );

    const menus: MenuDef[] = [
        {
            label: t("topBar.menu.file"),
            items: [
                {
                    label: t("topBar.menu.new"),
                    shortcut: "Ctrl+N",
                    action: handleNew,
                },
                { separator: true },
                {
                    label: t("topBar.menu.save"),
                    shortcut: "Ctrl+S",
                    action: handleSave,
                    disabled: !isAuthenticated,
                },
                {
                    label: t("topBar.menu.saveAs"),
                    action: handleSaveAs,
                    disabled: !isAuthenticated,
                },
                { separator: true },
                {
                    label: t("topBar.menu.export"),
                    shortcut: "Ctrl+Shift+E",
                    action: openExportDialog,
                },
                { label: t("topBar.menu.import"), action: handleImport },
            ],
        },
        {
            label: t("topBar.menu.edit"),
            items: [
                {
                    label: t("topBar.menu.undo"),
                    shortcut: "Ctrl+Z",
                    action: undo,
                    disabled: pastLen === 0,
                },
                {
                    label: t("topBar.menu.redo"),
                    shortcut: "Ctrl+Y",
                    action: redo,
                    disabled: futureLen === 0,
                },
                { separator: true },
                {
                    label: t("topBar.menu.copy"),
                    shortcut: "Ctrl+C",
                    action: copySelection,
                    disabled: selectionLen === 0,
                },
                {
                    label: t("topBar.menu.cut"),
                    shortcut: "Ctrl+X",
                    action: cutSelection,
                    disabled: selectionLen === 0,
                },
                {
                    label: t("topBar.menu.paste"),
                    shortcut: "Ctrl+V",
                    action: paste,
                    disabled: !hasClipboard,
                },
                { separator: true },
                {
                    label: t("topBar.menu.selectAll"),
                    shortcut: "Ctrl+A",
                    action: selectAll,
                },
                {
                    label: t("topBar.menu.delete"),
                    shortcut: "Del",
                    action: deleteSelection,
                    disabled: selectionLen === 0,
                },
                { separator: true },
                {
                    label: t("topBar.menu.saveSelectionAsObject"),
                    action: () => setSaveObjectOpen(true),
                    disabled: !isAuthenticated || !hasNodeSelection,
                },
                {
                    label: t("topBar.menu.groupIntoObject"),
                    action: () => groupSelectionIntoObject(),
                    disabled: !hasNodeSelection,
                },
            ],
        },
        {
            label: t("topBar.menu.view"),
            items: [
                {
                    label: t("topBar.menu.zoomIn"),
                    shortcut: "Ctrl++",
                    action: () => {},
                    disabled: true,
                },
                {
                    label: t("topBar.menu.zoomOut"),
                    shortcut: "Ctrl+-",
                    action: () => {},
                    disabled: true,
                },
                {
                    label: t("topBar.menu.fitView"),
                    shortcut: "Ctrl+0",
                    action: () => {},
                    disabled: true,
                },
                { separator: true },
                {
                    label: smoothAnimations
                        ? t("topBar.smoothAnimationsOn")
                        : t("topBar.smoothAnimationsOff"),
                    action: () => toggleSmoothAnimations(!smoothAnimations),
                },
                { separator: true },
                {
                    label: t("topBar.menu.arcStyle"),
                    submenu: EDGE_STYLE_OPTIONS.map((opt) => ({
                        label: `${opt.label}${edgeStyle === opt.value ? " ✓" : ""}`,
                        action: () => setEdgeStyle(opt.value),
                    })),
                },
                {
                    label: t("topBar.menu.frameStyle"),
                    submenu: FRAME_STYLE_OPTIONS.map((opt) => ({
                        label: `${opt.label}${frameStyle === opt.value ? " ✓" : ""}`,
                        action: () => setFrameStyle(opt.value),
                    })),
                },
            ],
        },
    ];

    menus.push(
        {
            label: t("review.menu"),
            items: [
                { label: t("review.open"), action: pickTrainingFile },
                {
                    label: t("review.start"),
                    action: () => useTrainingStore.getState().show(),
                },
            ],
        },
        {
            label: t("review.aiMenu"),
            items: [
                {
                    label: t("review.exportTitle"),
                    action: () => setTrainingExportOpen(true),
                },
            ],
        },
    );

    return (
        <>
            <header
                className={cn(
                    "flex h-9 shrink-0 items-center gap-1 border-b border-border",
                    "bg-surface-secondary px-2",
                )}
            >
                <nav className="flex items-center gap-0.5">
                    {menus.map((menu) => (
                        <MenuButton key={menu.label} menu={menu} />
                    ))}
                </nav>
                <div className="ml-4 flex items-center gap-2 text-sm">
                    <span className="font-medium text-text-primary">
                        {netName}
                    </span>
                    {dirty && (
                        <span className="text-xs text-amber-600 dark:text-amber-400">
                            ({t("topBar.unsaved")})
                        </span>
                    )}
                </div>
            </header>
            {exportDialogOpen && (
                <ExportDialogComponent onClose={closeExportDialog} />
            )}
            {trainingExportOpen && (
                <TrainingExportDialog
                    onClose={() => setTrainingExportOpen(false)}
                />
            )}
            {saveObjectOpen && (
                <SaveObjectDialog
                    onSave={handleSaveObject}
                    onClose={() => setSaveObjectOpen(false)}
                />
            )}
        </>
    );
}

function SubmenuItem({
    entry,
    onClose,
}: {
    entry: MenuSubmenu;
    onClose: () => void;
}) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    return (
        <div
            ref={ref}
            className="relative"
            onMouseEnter={() => setOpen(true)}
            onMouseLeave={() => setOpen(false)}
        >
            <button
                type="button"
                role="menuitem"
                aria-haspopup="menu"
                aria-expanded={open}
                className={cn(
                    "flex w-full items-center justify-between px-3 py-1.5",
                    "text-left text-xs transition-colors",
                    "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                )}
            >
                <span>{entry.label}</span>
                <ChevronRight size={12} className="ml-4 text-text-muted" />
            </button>
            {open && (
                <div
                    role="menu"
                    className={cn(
                        "absolute left-full top-0 z-50 min-w-[160px]",
                        "rounded-lg border border-border bg-surface py-1 shadow-lg",
                        "-mt-1 ml-0.5",
                    )}
                >
                    {entry.submenu.map((sub, i) =>
                        isSeparator(sub) ? (
                            <div
                                key={`sub-sep-${i}`}
                                className="my-1 h-px bg-border"
                                role="separator"
                            />
                        ) : isSubmenu(sub) ? null : (
                            <button
                                key={sub.label}
                                type="button"
                                role="menuitem"
                                disabled={sub.disabled}
                                onClick={() => {
                                    if (!sub.disabled) {
                                        sub.action();
                                        onClose();
                                    }
                                }}
                                className={cn(
                                    "flex w-full items-center justify-between px-3 py-1.5",
                                    "text-left text-xs transition-colors",
                                    sub.disabled
                                        ? "cursor-not-allowed text-text-muted/50"
                                        : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                                )}
                            >
                                <span>{sub.label}</span>
                                {sub.shortcut && (
                                    <span className="ml-6 text-[10px] text-text-muted">
                                        {sub.shortcut}
                                    </span>
                                )}
                            </button>
                        ),
                    )}
                </div>
            )}
        </div>
    );
}

function MenuButton({ menu }: { menu: MenuDef }) {
    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);

    const close = useCallback(() => setOpen(false), []);

    useEffect(() => {
        if (!open) return;
        function onClickOutside(e: MouseEvent) {
            if (ref.current && !ref.current.contains(e.target as Node)) {
                close();
            }
        }
        function onEscape(e: KeyboardEvent) {
            if (e.key === "Escape") close();
        }
        document.addEventListener("mousedown", onClickOutside);
        document.addEventListener("keydown", onEscape);
        return () => {
            document.removeEventListener("mousedown", onClickOutside);
            document.removeEventListener("keydown", onEscape);
        };
    }, [open, close]);

    return (
        <div ref={ref} className="relative">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className={cn(
                    "rounded px-2.5 py-1 text-xs font-medium transition-colors",
                    open
                        ? "bg-accent text-white"
                        : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                )}
            >
                {menu.label}
            </button>
            {open && (
                <div
                    role="menu"
                    className={cn(
                        "absolute left-0 top-full z-50 mt-0.5 min-w-[200px]",
                        "rounded-lg border border-border bg-surface py-1 shadow-lg",
                    )}
                >
                    {menu.items.map((entry, i) =>
                        isSeparator(entry) ? (
                            <div
                                key={`sep-${i}`}
                                className="my-1 h-px bg-border"
                                role="separator"
                            />
                        ) : isSubmenu(entry) ? (
                            <SubmenuItem
                                key={entry.label}
                                entry={entry}
                                onClose={close}
                            />
                        ) : (
                            <button
                                key={entry.label}
                                type="button"
                                role="menuitem"
                                disabled={entry.disabled}
                                onClick={() => {
                                    if (!entry.disabled) {
                                        entry.action();
                                        close();
                                    }
                                }}
                                className={cn(
                                    "flex w-full items-center justify-between px-3 py-1.5",
                                    "text-left text-xs transition-colors",
                                    entry.disabled
                                        ? "cursor-not-allowed text-text-muted/50"
                                        : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
                                )}
                            >
                                <span>{entry.label}</span>
                                {entry.shortcut && (
                                    <span className="ml-6 text-[10px] text-text-muted">
                                        {entry.shortcut}
                                    </span>
                                )}
                            </button>
                        ),
                    )}
                </div>
            )}
        </div>
    );
}
