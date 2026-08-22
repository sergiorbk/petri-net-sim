import { create } from "zustand";
import {
  listPetriObjects,
  getPetriObject,
  createPetriObject,
  deletePetriObject,
  updatePetriObject,
  type PetriObjectSummary,
  type PetriObjectDetail,
  type PetriObjectCreateRequest,
} from "@/lib/petri-objects-client";

interface PetriObjectState {
  items: PetriObjectSummary[];
  loading: boolean;
  error: string | null;

  detailCache: Record<string, PetriObjectDetail>;

  fetch: () => Promise<void>;
  getDetail: (id: string) => Promise<PetriObjectDetail | null>;
  create: (req: PetriObjectCreateRequest) => Promise<PetriObjectDetail | null>;
  rename: (id: string, name: string) => Promise<boolean>;
  remove: (id: string) => Promise<boolean>;
}

export const usePetriObjectStore = create<PetriObjectState>((set, get) => ({
  items: [],
  loading: false,
  error: null,
  detailCache: {},

  fetch: async () => {
    set({ loading: true, error: null });
    const result = await listPetriObjects();
    if (result.ok) {
      set({ items: result.data, loading: false });
    } else {
      set({ error: result.error, loading: false });
    }
  },

  getDetail: async (id) => {
    const cached = get().detailCache[id];
    if (cached) return cached;

    const result = await getPetriObject(id);
    if (result.ok) {
      set((s) => ({
        detailCache: { ...s.detailCache, [id]: result.data },
      }));
      return result.data;
    }
    return null;
  },

  create: async (req) => {
    const result = await createPetriObject(req);
    if (result.ok) {
      set((s) => ({
        items: [...s.items, result.data],
        detailCache: { ...s.detailCache, [result.data.id]: result.data },
        error: null,
      }));
      return result.data;
    }
    set({ error: result.error });
    return null;
  },

  rename: async (id, name) => {
    const result = await updatePetriObject(id, { name });
    if (result.ok) {
      set((s) => ({
        items: s.items.map((i) => (i.id === id ? { ...i, name } : i)),
        detailCache: {
          ...s.detailCache,
          ...(s.detailCache[id]
            ? { [id]: { ...s.detailCache[id], name } }
            : {}),
        },
      }));
      return true;
    }
    return false;
  },

  remove: async (id) => {
    const result = await deletePetriObject(id);
    if (result.ok) {
      set((s) => {
        const { [id]: _, ...rest } = s.detailCache;
        return {
          items: s.items.filter((i) => i.id !== id),
          detailCache: rest,
        };
      });
      return true;
    }
    return false;
  },
}));
