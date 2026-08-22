import { create } from "zustand";
import {
  listUserNets,
  createUserNet,
  deleteUserNet,
  updateUserNet,
  shareUserNet,
  getSharedNet,
  type SortBy,
  type NetVisibility,
  type UserNetSummary,
} from "@/lib/nets-client";
import { getItem, setItem } from "@/lib/storage";

const PAGE_SIZE = 24;
const SHARED_NETS_KEY = "shared-nets";

type NetFilter = "all" | "mine" | "shared";

interface UserNetsState {
  /** Backend-owned nets for the current user. */
  ownItems: UserNetSummary[];
  /** Nets added from share links (persisted in localStorage). */
  sharedItems: UserNetSummary[];
  /** Combined view based on active filter. */
  items: UserNetSummary[];

  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  hasMore: boolean;
  offset: number;
  sortBy: SortBy;
  filter: NetFilter;

  fetch: () => Promise<void>;
  loadMore: () => Promise<void>;
  setSortBy: (sort: SortBy) => void;
  setFilter: (filter: NetFilter) => void;
  invalidate: () => void;
  upsertSummary: (item: UserNetSummary) => void;
  create: (name: string, netData: object) => Promise<string>;
  remove: (id: string) => Promise<void>;
  rename: (id: string, name: string) => Promise<void>;
  shareNet: (id: string, visibility: NetVisibility) => Promise<string | null>;
  addSharedNet: (shareToken: string) => Promise<void>;
  removeSharedNet: (shareToken: string) => void;
}

function applyFilter(
  own: UserNetSummary[],
  shared: UserNetSummary[],
  filter: NetFilter,
): UserNetSummary[] {
  if (filter === "mine") return own;
  if (filter === "shared") return shared;
  return [...own, ...shared];
}

function loadSharedFromStorage(): UserNetSummary[] {
  return getItem<UserNetSummary[]>(SHARED_NETS_KEY, []);
}

function saveSharedToStorage(items: UserNetSummary[]): void {
  setItem(SHARED_NETS_KEY, items);
}

export const useUserNetsStore = create<UserNetsState>((set, get) => ({
  ownItems: [],
  sharedItems: loadSharedFromStorage(),
  items: loadSharedFromStorage(),
  loading: false,
  loadingMore: false,
  error: null,
  hasMore: false,
  offset: 0,
  sortBy: "updated_at",
  filter: "all",

  fetch: async () => {
    if (get().loading) return;
    set({ loading: true, error: null, ownItems: [], offset: 0, hasMore: false });
    const result = await listUserNets({ limit: PAGE_SIZE, offset: 0, sort_by: get().sortBy });
    if (result.ok) {
      const own = result.data.items;
      const shared = get().sharedItems;
      set({
        ownItems: own,
        items: applyFilter(own, shared, get().filter),
        hasMore: result.data.has_more,
        offset: own.length,
        loading: false,
      });
    } else {
      set({ error: result.error ?? "Failed to load nets", loading: false });
    }
  },

  loadMore: async () => {
    const { loadingMore, hasMore, offset, sortBy } = get();
    if (loadingMore || !hasMore) return;
    set({ loadingMore: true });
    const result = await listUserNets({ limit: PAGE_SIZE, offset, sort_by: sortBy });
    if (result.ok) {
      set((s) => {
        const own = [...s.ownItems, ...result.data.items];
        return {
          ownItems: own,
          items: applyFilter(own, s.sharedItems, s.filter),
          hasMore: result.data.has_more,
          offset: s.offset + result.data.items.length,
          loadingMore: false,
        };
      });
    } else {
      set({ loadingMore: false });
    }
  },

  setSortBy: (sort) => {
    if (get().sortBy === sort) return;
    set({ sortBy: sort });
    get().fetch();
  },

  setFilter: (filter) => {
    const { ownItems, sharedItems } = get();
    set({ filter, items: applyFilter(ownItems, sharedItems, filter) });
  },

  invalidate: () => {
    set({ offset: 0, hasMore: false });
    get().fetch();
  },

  upsertSummary: (item) =>
    set((s) => {
      const own = s.ownItems.some((i) => i.id === item.id)
        ? s.ownItems.map((i) => (i.id === item.id ? item : i))
        : [item, ...s.ownItems];
      return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
    }),

  create: async (name, netData) => {
    const tempId = `__tmp_${Date.now()}`;
    const now = new Date().toISOString();
    const optimistic: UserNetSummary = {
      id: tempId,
      name,
      created_at: now,
      updated_at: now,
      thumbnail: [],
      thumbnail_arcs: [],
    };
    set((s) => {
      const own = [optimistic, ...s.ownItems];
      return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
    });

    try {
      const result = await createUserNet({ name, net_data: netData as never });
      if (!result.ok) throw new Error(result.error ?? "Create failed");
      const created = result.data;
      const summary: UserNetSummary = {
        id: created.id,
        name: created.name,
        created_at: created.created_at,
        updated_at: created.updated_at,
        thumbnail: [],
        thumbnail_arcs: [],
        share_token: created.share_token,
        visibility: created.visibility as NetVisibility,
      };
      set((s) => {
        const own = s.ownItems.map((i) => (i.id === tempId ? summary : i));
        return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
      });
      return created.id;
    } catch (err) {
      set((s) => {
        const own = s.ownItems.filter((i) => i.id !== tempId);
        return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
      });
      throw err;
    }
  },

  remove: async (id) => {
    const snapshot = get().ownItems;
    set((s) => {
      const own = s.ownItems.filter((i) => i.id !== id);
      return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
    });
    try {
      const result = await deleteUserNet(id);
      if (!result.ok) throw new Error(result.error ?? "Delete failed");
    } catch (err) {
      set((s) => ({ ownItems: snapshot, items: applyFilter(snapshot, s.sharedItems, s.filter) }));
      throw err;
    }
  },

  rename: async (id, name) => {
    const snapshot = get().ownItems;
    set((s) => {
      const own = s.ownItems.map((i) => (i.id === id ? { ...i, name } : i));
      return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
    });
    try {
      const result = await updateUserNet(id, { name });
      if (!result.ok) throw new Error(result.error ?? "Rename failed");
    } catch (err) {
      set((s) => ({ ownItems: snapshot, items: applyFilter(snapshot, s.sharedItems, s.filter) }));
      throw err;
    }
  },

  shareNet: async (id, visibility) => {
    const result = await shareUserNet(id, visibility);
    if (!result.ok) return null;
    const { share_token } = result.data;
    set((s) => {
      const own = s.ownItems.map((i) =>
        i.id === id ? { ...i, share_token, visibility } : i,
      );
      return { ownItems: own, items: applyFilter(own, s.sharedItems, s.filter) };
    });
    return share_token;
  },

  addSharedNet: async (shareToken) => {
    const existing = get().sharedItems.find((i) => i.share_token === shareToken);
    if (existing) return;

    const result = await getSharedNet(shareToken);
    if (!result.ok) return;

    const net = result.data;
    const entry: UserNetSummary = {
      id: net.id,
      name: net.name,
      created_at: net.created_at,
      updated_at: net.updated_at,
      thumbnail: net.thumbnail,
      thumbnail_arcs: net.thumbnail_arcs,
      share_token: net.share_token,
      visibility: net.visibility,
      isShared: true,
    };
    set((s) => {
      const shared = [entry, ...s.sharedItems];
      saveSharedToStorage(shared);
      return { sharedItems: shared, items: applyFilter(s.ownItems, shared, s.filter) };
    });
  },

  removeSharedNet: (shareToken) => {
    set((s) => {
      const shared = s.sharedItems.filter((i) => i.share_token !== shareToken);
      saveSharedToStorage(shared);
      return { sharedItems: shared, items: applyFilter(s.ownItems, shared, s.filter) };
    });
  },
}));
