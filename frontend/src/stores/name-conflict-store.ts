import { create } from "zustand";
import { getItem, setItem } from "@/lib/storage";
import { suggestedRenames, type NameConflict } from "@/lib/petri-names";

/**
 * What to do when an element is given a name the canvas already uses.
 *
 * - `ask`  show the warning, with a field for another name (default)
 * - `auto` pick the next free `name_N` without asking
 * - `keep` allow the duplicate without asking
 *
 * Per browser, like the theme: it only steers the editor's own behaviour and
 * the server never reads it, so it does not belong on the account.
 */
export type DuplicateNamePolicy = "ask" | "auto" | "keep";

const POLICIES: readonly DuplicateNamePolicy[] = ["ask", "auto", "keep"];
const STORAGE_KEY = "duplicate-name-policy";

function readPolicy(): DuplicateNamePolicy {
  const saved = getItem<string>(STORAGE_KEY, "ask");
  // Anything unrecognised (an older build, a hand-edited value) falls back to
  // asking: the safe choice is the one that shows the user what is happening.
  return (POLICIES as readonly string[]).includes(saved) ? (saved as DuplicateNamePolicy) : "ask";
}

/** What the user (or the saved policy) decided about a batch of conflicts. */
export type NameDecision =
  | { kind: "rename"; renames: Map<string, string> }
  | { kind: "keep" }
  | { kind: "cancel" };

export interface NameResolutionRequest {
  conflicts: NameConflict[];
  /**
   * Names an edited value must avoid. Fused partners of a renamed place are
   * not in here: they are allowed to share its name.
   */
  taken: ReadonlySet<string>;
  onDecision: (decision: NameDecision) => void;
}

interface NameConflictState {
  policy: DuplicateNamePolicy;
  /** The dialog's request while one is open; null otherwise. */
  pending: NameResolutionRequest | null;

  setPolicy: (policy: DuplicateNamePolicy) => void;
  /**
   * Settle a batch of conflicts by the saved policy, or park it for the
   * dialog. `onDecision` runs exactly once, synchronously for `auto` and
   * `keep`, and after the user answers for `ask`.
   */
  resolve: (
    conflicts: NameConflict[],
    taken: ReadonlySet<string>,
    onDecision: (decision: NameDecision) => void,
  ) => void;
  /**
   * The dialog's answer. `remember` writes `auto` / `keep` back as the policy
   * so the next conflict is settled silently; an explicit rename or a cancel
   * never changes it.
   */
  answer: (
    choice: "auto" | "keep" | "cancel" | { rename: Map<string, string> },
    remember?: boolean,
  ) => void;
}

export const useNameConflictStore = create<NameConflictState>((set, get) => ({
  policy: readPolicy(),
  pending: null,

  setPolicy: (policy) => {
    setItem(STORAGE_KEY, policy);
    set({ policy });
  },

  resolve: (conflicts, taken, onDecision) => {
    const { policy, pending } = get();
    if (conflicts.length === 0) {
      onDecision({ kind: "keep" });
      return;
    }
    if (policy === "auto") {
      onDecision({ kind: "rename", renames: suggestedRenames(conflicts) });
      return;
    }
    if (policy === "keep") {
      onDecision({ kind: "keep" });
      return;
    }
    // One dialog at a time. A second request while one is open can only come
    // from a gesture that slipped past the modal; the older one is cancelled
    // rather than silently dropped, so its caller is not left waiting.
    pending?.onDecision({ kind: "cancel" });
    set({ pending: { conflicts, taken, onDecision } });
  },

  answer: (choice, remember = false) => {
    const { pending } = get();
    if (!pending) return;
    set({ pending: null });

    if (choice === "cancel") {
      pending.onDecision({ kind: "cancel" });
      return;
    }
    if (choice === "auto") {
      if (remember) get().setPolicy("auto");
      pending.onDecision({ kind: "rename", renames: suggestedRenames(pending.conflicts) });
      return;
    }
    if (choice === "keep") {
      if (remember) get().setPolicy("keep");
      pending.onDecision({ kind: "keep" });
      return;
    }
    pending.onDecision({ kind: "rename", renames: choice.rename });
  },
}));
