import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { useUserNetsStore } from "@/stores/user-nets-store";
import { getUserNet } from "@/lib/nets-client";
import { useEditorStore } from "@/stores/editor-store";
import { randomNetName } from "@/lib/random-net-name";
import type { PetriNetData } from "@/types/petri";

interface Props {
  onCreated: (id: string) => void;
  onClose: () => void;
}

export function NewNetDialog({ onCreated, onClose }: Props) {
  const { t } = useTranslation();
  const nameId = useId();
  const baseId = useId();
  const nameRef = useRef<HTMLInputElement>(null);

  const items = useUserNetsStore((s) => s.items);
  const create = useUserNetsStore((s) => s.create);

  const [name, setName] = useState(() => randomNetName());
  const [baseNetId, setBaseNetId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    nameRef.current?.select();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;

    setBusy(true);
    setError(null);
    try {
      let netData: PetriNetData = { name: trimmed, places: [], transitions: [], arcs: [] };

      if (baseNetId) {
        const res = await getUserNet(baseNetId);
        if (!res.ok) throw new Error(res.error ?? t("shared.failedToLoad"));
        netData = { ...res.data.net_data, name: trimmed };
      }

      const id = await create(trimmed, netData);

      useEditorStore.getState().setNet(netData);
      useEditorStore.setState({ cloudNetId: id });

      onCreated(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-6 shadow-xl">
        <h2 className="mb-5 text-base font-semibold text-text-primary">{t("dialog.newNet.title")}</h2>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor={nameId} className="text-xs text-text-secondary">
              {t("common.name")}
            </label>
            <input
              id={nameId}
              ref={nameRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className={cn(
                "w-full rounded-lg border border-border bg-surface-secondary",
                "px-3 py-2 text-sm text-text-primary outline-none",
                "focus:border-accent focus:ring-1 focus:ring-accent",
              )}
              placeholder={t("dialog.newNet.namePlaceholder")}
              required
              maxLength={255}
            />
          </div>

          {items.length > 0 && (
            <div className="flex flex-col gap-1.5">
              <label htmlFor={baseId} className="text-xs text-text-secondary">
                {t("dialog.newNet.basedOn")}
              </label>
              <select
                id={baseId}
                value={baseNetId}
                onChange={(e) => setBaseNetId(e.target.value)}
                className={cn(
                  "w-full rounded-lg border border-border bg-surface-secondary",
                  "px-3 py-2 text-sm text-text-primary outline-none",
                  "focus:border-accent focus:ring-1 focus:ring-accent",
                )}
              >
                <option value="">{t("dialog.newNet.emptyNet")}</option>
                {items.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {error && (
            <p className="text-xs text-red-500">{error}</p>
          )}

          <div className="mt-1 flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className={cn(
                "rounded-lg px-4 py-2 text-sm text-text-secondary",
                "transition-colors hover:bg-surface-hover hover:text-text-primary",
              )}
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className={cn(
                "rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white",
                "transition-opacity disabled:opacity-50",
              )}
            >
              {busy ? t("common.creating") : t("common.create")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
