import { useCallback, useEffect, useRef, useState } from "react";
import { GripVertical, MoreVertical, Trash2, Pencil } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth-store";
import { usePetriObjectStore } from "@/stores/petri-object-store";
import type { PetriObjectSummary } from "@/lib/petri-objects-client";
import { setDraggingTemplate } from "@/lib/object-drag-state";
import { ObjectHoverPreview } from "./ObjectHoverPreview";
import { PaletteSection } from "./PaletteSection";
import { CanvasObjectList } from "./CanvasObjectList";

export function ObjectPalette() {
  const { t } = useTranslation();
  const items = usePetriObjectStore((s) => s.items);
  const loading = usePetriObjectStore((s) => s.loading);
  const error = usePetriObjectStore((s) => s.error);
  const fetchObjects = usePetriObjectStore((s) => s.fetch);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);

  useEffect(() => {
    fetchObjects();
  }, [fetchObjects]);

  const builtins = items.filter((i) => i.is_builtin);
  const custom = items.filter((i) => !i.is_builtin);

  const [builtinExpanded, setBuiltinExpanded] = useState(false);
  const [customExpanded, setCustomExpanded] = useState(true);

  return (
    <div className="flex h-full flex-col overflow-y-auto py-1">
      {/* What is on this canvas comes first — it's the list the user just
          added to — with the reusable library below it. */}
      <CanvasObjectList />
      {loading && (
        <p className="px-2 py-3 text-center text-[11px] text-text-muted">
          {t("common.loading")}
        </p>
      )}
      {error && (
        <p className="px-2 py-3 text-center text-[11px] text-red-500">
          {error}
        </p>
      )}
      {!loading && (
        <>
          <PaletteSection
            label={t("objectPalette.builtIn")}
            count={builtins.length}
            expanded={builtinExpanded}
            onToggle={() => setBuiltinExpanded((v) => !v)}
          >
            {builtins.map((obj) => (
              <ObjectItem key={obj.id} item={obj} />
            ))}
          </PaletteSection>

          {isAuthenticated && (
            <PaletteSection
              label={t("objectPalette.myObjects")}
              count={custom.length}
              expanded={customExpanded}
              onToggle={() => setCustomExpanded((v) => !v)}
            >
              {custom.length === 0 ? (
                <p className="px-2 py-2 text-[10px] text-text-muted">
                  <span className="block">{t("objectPalette.noCustomObjectsLine1")}</span>
                  <span className="block">{t("objectPalette.noCustomObjectsLine2")}</span>
                </p>
              ) : (
                custom.map((obj) => (
                  <ObjectItem key={obj.id} item={obj} editable />
                ))
              )}
            </PaletteSection>
          )}
        </>
      )}
    </div>
  );
}

function ObjectItem({
  item,
  editable = false,
}: {
  item: PetriObjectSummary;
  editable?: boolean;
}) {
  const { t } = useTranslation();
  const getDetail = usePetriObjectStore((s) => s.getDetail);
  const renameObject = usePetriObjectStore((s) => s.rename);
  const removeObject = usePetriObjectStore((s) => s.remove);

  const [hoverAnchor, setHoverAnchor] = useState<{ x: number; y: number } | null>(null);
  const [previewDetail, setPreviewDetail] = useState<Awaited<ReturnType<typeof getDetail>> | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const itemRef = useRef<HTMLDivElement>(null);

  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const onPointerEnter = useCallback(() => {
    hoverTimer.current = setTimeout(async () => {
      const detail = await getDetail(item.id);
      if (detail && itemRef.current) {
        const rect = itemRef.current.getBoundingClientRect();
        setHoverAnchor({ x: rect.right + 8, y: rect.top });
        setPreviewDetail(detail);
      }
    }, 400);
  }, [getDetail, item.id]);

  const onPointerLeave = useCallback(() => {
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
    setHoverAnchor(null);
    setPreviewDetail(null);
  }, []);

  const onDragStart = useCallback(
    (e: React.DragEvent) => {
      e.dataTransfer.setData("application/petri-object-id", item.id);
      e.dataTransfer.effectAllowed = "copy";
      // Pre-fetch template for the ghost preview in EditorCanvas.
      // Hit the cache immediately if the user hovered; starts a fetch otherwise.
      getDetail(item.id).then((detail) => {
        if (detail) setDraggingTemplate(detail.template_data);
      });
    },
    [item.id, getDetail],
  );

  const onDragEnd = useCallback(() => {
    setDraggingTemplate(null);
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [menuOpen]);

  const handleRename = useCallback(async () => {
    setMenuOpen(false);
    const newName = window.prompt(t("objectPalette.confirmRename"), item.name);
    if (newName && newName !== item.name) {
      await renameObject(item.id, newName);
    }
  }, [item.id, item.name, renameObject, t]);

  const handleDelete = useCallback(async () => {
    setMenuOpen(false);
    if (window.confirm(t("objectPalette.confirmDelete", { name: item.name }))) {
      await removeObject(item.id);
    }
  }, [item.id, item.name, removeObject, t]);

  return (
    <>
      <div
        ref={itemRef}
        draggable
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onPointerEnter={onPointerEnter}
        onPointerLeave={onPointerLeave}
        className={cn(
          "group flex items-center gap-1.5 px-2 py-1",
          "cursor-grab text-[11px] text-text-secondary",
          "hover:bg-surface-hover hover:text-text-primary",
          "active:cursor-grabbing",
        )}
      >
        <GripVertical size={12} className="shrink-0 text-text-muted/50 group-hover:text-text-muted" />
        <span className="min-w-0 flex-1 truncate">{item.name}</span>
        {editable && (
          <div ref={menuRef} className="relative">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setMenuOpen((v) => !v);
              }}
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded",
                "opacity-0 transition-opacity group-hover:opacity-100",
                "hover:bg-surface-hover",
              )}
            >
              <MoreVertical size={12} />
            </button>
            {menuOpen && (
              <div
                className={cn(
                  "absolute right-0 top-full z-50 mt-0.5 min-w-[120px]",
                  "rounded-md border border-border bg-surface py-0.5 shadow-lg",
                )}
              >
                <button
                  type="button"
                  onClick={handleRename}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-text-secondary hover:bg-surface-hover"
                >
                  <Pencil size={11} /> {t("objectPalette.rename")}
                </button>
                <button
                  type="button"
                  onClick={handleDelete}
                  className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-red-500 hover:bg-surface-hover"
                >
                  <Trash2 size={11} /> {t("objectPalette.delete")}
                </button>
              </div>
            )}
          </div>
        )}
      </div>
      {hoverAnchor && previewDetail && (
        <ObjectHoverPreview detail={previewDetail} anchor={hoverAnchor} />
      )}
    </>
  );
}
