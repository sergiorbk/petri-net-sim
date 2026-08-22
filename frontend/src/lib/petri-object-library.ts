import { useEditorStore } from "@/stores/editor-store";
import { usePetriObjectStore } from "@/stores/petri-object-store";
import { extractObjectAsTemplate, getObjects } from "@/lib/petri-object-model";

export type SaveObjectToLibraryResult =
  | { ok: true; id: string; name: string }
  | { ok: false; reason: "missing" | "empty" | "failed"; error?: string };

/**
 * Publish one canvas object into the cross-canvas Petri-object library, so it
 * can be dropped onto any other canvas later. The frame remembers which
 * library entry it became (templateId), keeping the two associated.
 *
 * Returns a result rather than showing anything itself — the wording of the
 * outcome belongs to whichever surface invoked it.
 */
export async function saveCanvasObjectToLibrary(
  objectId: string,
): Promise<SaveObjectToLibraryResult> {
  const net = useEditorStore.getState().net;
  const frame = getObjects(net).find((o) => o.id === objectId);
  if (!frame) return { ok: false, reason: "missing" };

  // The whole subtree travels: a nested Petri-object and the links inside
  // are part of what the object IS, not canvas decoration.
  const template = extractObjectAsTemplate(net, objectId);
  if (!template) return { ok: false, reason: "empty" };

  const created = await usePetriObjectStore.getState().create({
    name: frame.name,
    description: null,
    template_data: { name: frame.name, ...template },
  });
  if (!created) {
    return {
      ok: false,
      reason: "failed",
      error: usePetriObjectStore.getState().error ?? undefined,
    };
  }

  useEditorStore.getState().setObjectTemplateId(objectId, created.id);
  return { ok: true, id: created.id, name: frame.name };
}
