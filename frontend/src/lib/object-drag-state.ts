import type { PetriObjectTemplate } from "./petri-objects-client";

let _template: PetriObjectTemplate | null = null;

export function setDraggingTemplate(t: PetriObjectTemplate | null): void {
  _template = t;
}

export function getDraggingTemplate(): PetriObjectTemplate | null {
  return _template;
}
