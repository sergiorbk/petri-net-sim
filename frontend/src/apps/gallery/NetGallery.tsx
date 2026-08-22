import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus, Pencil, Share2, Trash2, Upload, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUserNetsStore } from "@/stores/user-nets-store";
import { useAuthStore } from "@/stores/auth-store";
import { useEditorStore } from "@/stores/editor-store";
import type { SortBy, UserNetSummary } from "@/lib/nets-client";
import { parsePnml, summarizeImportWarnings } from "@/lib/pnml-import";
import { toast } from "@/stores/toast-store";
import { NetAvatar } from "./NetAvatar";
import { NewNetDialog } from "./NewNetDialog";
import { DropdownMenu } from "@/components/common/DropdownMenu";
import { NetShareDialog } from "@/components/gallery/NetShareDialog";

function pickPnmlFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pnml";
    input.style.cssText = "position:fixed;top:-9999px;left:-9999px;opacity:0";
    document.body.appendChild(input);
    const cleanup = () => {
      if (input.parentNode) document.body.removeChild(input);
    };
    input.addEventListener("change", () => {
      const file = input.files?.[0] ?? null;
      cleanup();
      resolve(file);
    });
    input.addEventListener("cancel", () => {
      cleanup();
      resolve(null);
    });
    input.click();
  });
}

/**
 * Sharing a net means handing it to somebody else, and a single-user
 * deployment has no somebody else: the share link would resolve to the
 * only account there is. Every control for it is hidden rather than
 * disabled -- a disabled control is a promise that it might work.
 */
function useSharingAvailable(): boolean {
  return useAuthStore((s) => s.authMode) !== "single_user";
}

export function NetGallery() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const sharingAvailable = useSharingAvailable();

  const create = useUserNetsStore((s) => s.create);
  const items = useUserNetsStore((s) => s.items);
  const loading = useUserNetsStore((s) => s.loading);
  const loadingMore = useUserNetsStore((s) => s.loadingMore);
  const hasMore = useUserNetsStore((s) => s.hasMore);
  const error = useUserNetsStore((s) => s.error);
  const sortBy = useUserNetsStore((s) => s.sortBy);
  const filter = useUserNetsStore((s) => s.filter);
  const fetch = useUserNetsStore((s) => s.fetch);
  const loadMore = useUserNetsStore((s) => s.loadMore);
  const setSortBy = useUserNetsStore((s) => s.setSortBy);
  const setFilter = useUserNetsStore((s) => s.setFilter);

  const [newNetOpen, setNewNetOpen] = useState(false);
  const [importing, setImporting] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const handleImport = useCallback(async () => {
    if (importing) return;
    const file = await pickPnmlFile();
    if (!file) return;
    setImporting(true);
    try {
      const text = await file.text();
      const { data, warnings } = parsePnml(text);
      if (warnings.length > 0) {
        console.warn("PNML import warnings:", warnings);
        toast(summarizeImportWarnings(warnings), "warning");
      }
      const baseName = file.name.replace(/\.pnml$/i, "") || data.name || "Imported";
      const netData = { ...data, name: baseName };
      const id = await create(baseName, netData);
      useEditorStore.getState().setNet(netData);
      useEditorStore.setState({ cloudNetId: id });
      navigate(`/nets/${id}`);
    } catch (err) {
      toast(err instanceof Error ? err.message : String(err), "error");
    } finally {
      setImporting(false);
    }
  }, [create, importing, navigate]);

  useEffect(() => {
    if (isAuthenticated) fetch();
  }, [fetch, isAuthenticated]);

  useEffect(() => {
    if (!hasMore || loadingMore || filter === "shared") return;
    const el = sentinelRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) loadMore(); },
      { threshold: 0.1 },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasMore, loadingMore, loadMore, filter]);

  const handleCreated = useCallback(
    (id: string) => {
      setNewNetOpen(false);
      navigate(`/nets/${id}`);
    },
    [navigate],
  );

  const handleOpen = useCallback(
    (item: UserNetSummary) => {
      if (item.isShared && item.share_token) {
        navigate(`/nets/share/${item.share_token}`);
      } else {
        navigate(`/nets/${item.id}`);
      }
    },
    [navigate],
  );

  const SORT_OPTIONS: { value: SortBy; label: string }[] = [
    { value: "updated_at", label: t("gallery.sort.updatedAt") },
    { value: "created_at", label: t("gallery.sort.createdAt") },
  ];

  const FILTER_OPTIONS = [
    { value: "all" as const, label: t("gallery.filter.all") },
    { value: "mine" as const, label: t("gallery.filter.mine") },
    // "Shared with me" cannot hold anything when there is only one account.
    ...(sharingAvailable
      ? [{ value: "shared" as const, label: t("gallery.filter.shared") }]
      : []),
  ];

  if (!isAuthenticated) {
    return <GuestState onLogin={() => navigate("/login")} />;
  }

  return (
    <div className="flex h-full flex-col bg-surface">
      <header className="flex h-14 shrink-0 items-center border-b border-border px-6">
        <div className="flex items-center gap-4">
          {/* The two actions stand where the page title used to: the route is
              already named in the activity bar, and this is the first thing a
              reader comes here to do. */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setNewNetOpen(true)}
              className={cn(
                "flex items-center gap-1.5 rounded-lg bg-accent px-3.5 py-1.5",
                "text-xs font-medium text-white transition-opacity hover:opacity-90",
              )}
            >
              <Plus size={14} />
              {t("gallery.newNet")}
            </button>
            <button
              type="button"
              onClick={handleImport}
              disabled={importing}
              className={cn(
                "flex items-center gap-1.5 rounded-lg border border-border bg-surface-secondary px-3.5 py-1.5",
                "text-xs font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              <Upload size={14} />
              {t("gallery.import")}
            </button>
          </div>

          <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface-secondary p-0.5">
            {FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFilter(opt.value)}
                className={cn(
                  "rounded px-2.5 py-1 text-xs transition-colors",
                  filter === opt.value
                    ? "bg-surface text-text-primary font-medium shadow-sm"
                    : "text-text-muted hover:text-text-secondary",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {filter !== "shared" && (
            <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface-secondary p-0.5">
              {SORT_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setSortBy(opt.value)}
                  className={cn(
                    "rounded px-2.5 py-1 text-xs transition-colors",
                    sortBy === opt.value
                      ? "bg-surface text-text-primary font-medium shadow-sm"
                      : "text-text-muted hover:text-text-secondary",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}
        </div>

      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-6">
        {loading && <LoadingSkeleton />}
        {error && (
          <p className="text-center text-sm text-red-500">{error}</p>
        )}
        {!loading && !error && items.length === 0 && (
          <EmptyState filter={filter} onNew={() => setNewNetOpen(true)} />
        )}
        {items.length > 0 && (
          <>
            <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
              {items.map((item) => (
                <NetCard
                  key={item.isShared ? `shared-${item.share_token}` : item.id}
                  item={item}
                  sortBy={sortBy}
                  onOpen={handleOpen}
                />
              ))}
            </ul>
            <div ref={sentinelRef} className="h-px" />
            {loadingMore && (
              <div className="mt-6 flex justify-center">
                <LoadingMoreSpinner />
              </div>
            )}
          </>
        )}
      </div>

      {newNetOpen && (
        <NewNetDialog
          onCreated={handleCreated}
          onClose={() => setNewNetOpen(false)}
        />
      )}
    </div>
  );
}

function NetCard({
  item,
  sortBy,
  onOpen,
}: {
  item: UserNetSummary;
  sortBy: SortBy;
  onOpen: (item: UserNetSummary) => void;
}) {
  const { t } = useTranslation();
  const remove = useUserNetsStore((s) => s.remove);
  const rename = useUserNetsStore((s) => s.rename);
  const removeSharedNet = useUserNetsStore((s) => s.removeSharedNet);
  // Where the menu was asked for, or null when it is closed. A card's
  // actions used to hang off a three-dot button that only appeared on
  // hover -- invisible until pointed at, and absent entirely on a touch
  // screen. A right-click is where anyone already looks for what can be
  // done to a thing, and it needs no corner of the card to live in.
  const [menuAt, setMenuAt] = useState<{ x: number; y: number } | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const sharingAvailable = useSharingAvailable();


  const handleRename = useCallback(async () => {
    setMenuAt(null);
    const next = window.prompt(t("gallery.card.confirmRename"), item.name);
    if (next?.trim() && next.trim() !== item.name) {
      await rename(item.id, next.trim());
    }
  }, [item.id, item.name, rename, t]);

  const handleDelete = useCallback(async () => {
    setMenuAt(null);
    if (!window.confirm(t("gallery.card.confirmDelete", { name: item.name }))) return;
    await remove(item.id);
  }, [item.id, item.name, remove, t]);

  const handleRemoveShared = useCallback(() => {
    setMenuAt(null);
    if (item.share_token) removeSharedNet(item.share_token);
  }, [item.share_token, removeSharedNet]);

  const dateLabel = sortBy === "created_at" ? t("gallery.card.created") : t("gallery.card.modified");
  const dateValue = new Date(
    sortBy === "created_at" ? item.created_at : item.updated_at,
  ).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  return (
    <li>
      <article
        className={cn(
          "group relative flex cursor-pointer flex-col",
          "rounded-xl border border-border bg-surface-secondary",
          "transition-shadow hover:shadow-md hover:border-accent/40",
        )}
        onClick={() => onOpen(item)}
        onContextMenu={(e) => {
          e.preventDefault();
          setMenuAt({ x: e.clientX, y: e.clientY });
        }}
      >
        <div className="flex aspect-[16/10] items-center justify-center overflow-hidden rounded-t-xl bg-surface-secondary">
          <NetAvatar seed={item.id} className="h-full w-full" />
        </div>

        <div className="relative px-3 py-2.5">
          <div className="flex flex-col items-center gap-0.5 text-center">
            <div className="flex max-w-full items-center justify-center gap-1.5">
              {item.isShared && (
                <Users size={12} className="shrink-0 text-accent" />
              )}
              <p className="truncate text-xs font-medium text-text-primary">
                {item.name}
              </p>
            </div>
            <p className="text-[10px] text-text-muted">
              {dateLabel} {dateValue}
            </p>
          </div>

        </div>
      </article>

      <DropdownMenu
        open={menuAt !== null}
        onClose={() => setMenuAt(null)}
        position={menuAt}
        items={
          item.isShared
            ? [{
                key: "remove-shared",
                label: t("gallery.card.removeFromGallery"),
                icon: <Trash2 size={13} />,
                danger: true,
                onClick: handleRemoveShared,
              }]
            : [
                ...(sharingAvailable
                  ? [{
                      key: "share",
                      label: t("gallery.card.share"),
                      icon: <Share2 size={13} />,
                      onClick: () => { setMenuAt(null); setShareOpen(true); },
                    }]
                  : []),
                {
                  key: "rename",
                  label: t("gallery.card.rename"),
                  icon: <Pencil size={13} />,
                  onClick: handleRename,
                },
                {
                  key: "delete",
                  label: t("gallery.card.delete"),
                  icon: <Trash2 size={13} />,
                  danger: true,
                  onClick: handleDelete,
                },
              ]
        }
      />

      {shareOpen && sharingAvailable && (
        <NetShareDialog net={item} onClose={() => setShareOpen(false)} />
      )}
    </li>
  );
}

function EmptyState({ filter, onNew }: { filter: string; onNew: () => void }) {
  const { t } = useTranslation();
  if (filter === "shared") {
    return (
      <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
        <p className="text-sm font-medium text-text-primary">{t("gallery.empty.noShared")}</p>
        <p className="max-w-xs text-xs text-text-muted">{t("gallery.empty.noSharedDesc")}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <p className="text-sm font-medium text-text-primary">{t("gallery.empty.noNets")}</p>
      <p className="max-w-xs text-xs text-text-muted">{t("gallery.empty.noNetsDesc")}</p>
      <button
        type="button"
        onClick={onNew}
        className="mt-2 flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
      >
        <Plus size={14} /> {t("gallery.newNet")}
      </button>
    </div>
  );
}

function GuestState({ onLogin }: { onLogin: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <p className="text-sm font-medium text-text-primary">{t("gallery.guest.title")}</p>
      <button
        type="button"
        onClick={onLogin}
        className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:opacity-90"
      >
        {t("gallery.guest.signIn")}
      </button>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <ul className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
      {Array.from({ length: 8 }).map((_, i) => (
        <li key={i}>
          <div className="animate-pulse rounded-xl border border-border bg-surface-secondary">
            <div className="aspect-[16/10] rounded-t-xl bg-surface-hover" />
            <div className="px-3 py-2.5">
              <div className="mb-1.5 h-3 w-3/4 rounded bg-surface-hover" />
              <div className="h-2.5 w-1/2 rounded bg-surface-hover" />
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}

function LoadingMoreSpinner() {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-2 text-xs text-text-muted">
      <svg
        className="h-4 w-4 animate-spin"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4l3-3-3-3V4a10 10 0 00-10 10h4z" />
      </svg>
      {t("gallery.loadingMore")}
    </div>
  );
}
