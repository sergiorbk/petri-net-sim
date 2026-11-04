import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { nextFreeName } from "@/lib/petri-names";
import { useNameConflictStore } from "@/stores/name-conflict-store";

/**
 * The warning shown when a name is already used on the canvas. It is mounted
 * once, next to the editor, and driven entirely by the name-conflict store:
 * whoever hit the clash parked a request there and is waiting for the answer.
 *
 * The user can type another name per row, let the editor pick (`name_2`, ...),
 * or keep the duplicate. "Remember my choice" turns the last two into the
 * saved policy, which Settings can change back.
 */
export function DuplicateNameDialog() {
  const pending = useNameConflictStore((s) => s.pending);
  if (!pending) return null;
  // Keyed on the request so a second one starts with fresh fields.
  return <DialogBody key={pending.conflicts.map((c) => c.ids.join()).join("|")} />;
}

function DialogBody() {
  const { t } = useTranslation();
  const pending = useNameConflictStore((s) => s.pending)!;
  const answer = useNameConflictStore((s) => s.answer);
  const { conflicts, taken } = pending;

  const [edits, setEdits] = useState<string[]>(() => conflicts.map(() => ""));
  const [remember, setRemember] = useState(false);
  const firstInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    firstInput.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") answer("cancel");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [answer]);

  // Per row: what it will be called, and what is wrong with an edited value.
  // A row left empty takes the next free name that dodges everything typed,
  // so a custom "Queue_2" cannot be stolen by another row's suggestion.
  const resolved = useMemo(() => {
    const typed = edits.map((value) => value.trim());
    const used = new Set<string>(taken);
    typed.forEach((value) => value && used.add(value));
    return conflicts.map((conflict, index) => {
      const value = typed[index];
      if (!value) {
        const name = nextFreeName(conflict.name, used);
        used.add(name);
        return { name, error: null as string | null };
      }
      let error: string | null = null;
      if (taken.has(value)) error = "nameConflict.errorTaken";
      else if (typed.some((other, j) => j !== index && other === value)) {
        error = "nameConflict.errorRepeated";
      }
      return { name: value, error };
    });
  }, [edits, conflicts, taken]);

  const invalid = resolved.some((r) => r.error !== null);
  const single = conflicts.length === 1;

  function applyEdits() {
    if (invalid) return;
    const renames = new Map<string, string>();
    conflicts.forEach((conflict, index) => {
      for (const id of conflict.ids) renames.set(id, resolved[index].name);
    });
    answer({ rename: renames });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) answer("cancel");
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="duplicate-name-title"
        className="w-full max-w-lg rounded-xl border border-border bg-surface p-6 shadow-xl"
      >
        <h2 id="duplicate-name-title" className="mb-2 text-base font-semibold text-text-primary">
          {single ? t("nameConflict.title") : t("nameConflict.titleMany")}
        </h2>
        <p className="mb-4 text-sm text-text-secondary">
          {single
            ? t("nameConflict.bodyOne", { name: conflicts[0].name })
            : t("nameConflict.bodyMany", { count: conflicts.length })}
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            applyEdits();
          }}
          className="flex flex-col gap-4"
        >
          <ul className="flex max-h-64 flex-col gap-3 overflow-y-auto pr-1">
            {conflicts.map((conflict, index) => (
              <li key={conflict.ids.join()} className="flex flex-col gap-1">
                <div className="flex items-baseline gap-2 text-xs text-text-secondary">
                  <span className="rounded bg-surface-secondary px-1.5 py-0.5">
                    {t(`nameConflict.kind.${conflict.kind}`)}
                  </span>
                  <span className="truncate font-medium text-text-primary">{conflict.name}</span>
                </div>
                <input
                  ref={index === 0 ? firstInput : undefined}
                  value={edits[index]}
                  onChange={(e) =>
                    setEdits((prev) => prev.map((v, i) => (i === index ? e.target.value : v)))
                  }
                  placeholder={resolved[index].name}
                  aria-label={t("nameConflict.newNameFor", { name: conflict.name })}
                  aria-invalid={resolved[index].error !== null}
                  maxLength={255}
                  className={cn(
                    "w-full rounded-lg border bg-surface-secondary px-3 py-2 text-sm",
                    "text-text-primary outline-none focus:ring-1",
                    resolved[index].error
                      ? "border-red-500 focus:border-red-500 focus:ring-red-500"
                      : "border-border focus:border-accent focus:ring-accent",
                  )}
                />
                {resolved[index].error && (
                  <p className="text-xs text-red-500">{t(resolved[index].error!)}</p>
                )}
              </li>
            ))}
          </ul>

          <p className="text-xs text-text-muted">{t("nameConflict.hint")}</p>

          <label className="flex items-center gap-2 text-sm text-text-secondary">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
              className="h-4 w-4 accent-[var(--color-accent)]"
            />
            {t("nameConflict.remember")}
          </label>

          <div className="mt-1 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => answer("cancel")}
              className="rounded-lg px-4 py-2 text-sm text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              onClick={() => answer("keep", remember)}
              className="rounded-lg px-4 py-2 text-sm text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary"
            >
              {t("nameConflict.keep")}
            </button>
            <button
              type="button"
              onClick={() => answer("auto", remember)}
              className="rounded-lg border border-border px-4 py-2 text-sm text-text-primary transition-colors hover:bg-surface-hover"
            >
              {t("nameConflict.auto")}
            </button>
            <button
              type="submit"
              disabled={invalid}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-opacity disabled:opacity-50"
            >
              {t("nameConflict.apply")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
