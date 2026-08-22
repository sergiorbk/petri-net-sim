import { useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { createUserNet } from "@/lib/nets-client";
import { toast } from "@/stores/toast-store";
import type { PetriNetData } from "@/types/petri";

/**
 * Fork a chat-generated snapshot into the user's "My Nets" library and open
 * it in the editor. Server creates a fresh mutable user_net row with
 * origin_snapshot_id pointing to the source NetSnapshot. Duplicates are
 * allowed — each click creates a new row.
 */
export function useForkToUserNet() {
  const navigate = useNavigate();
  const { t } = useTranslation();

  const forkNet = useCallback(
    async (name: string, net: PetriNetData, snapshotId?: string) => {
      const named: PetriNetData = { ...net, name };
      const result = await createUserNet({
        name,
        net_data: named,
        origin_snapshot_id: snapshotId ?? null,
      });
      if (result.ok) {
        navigate(`/nets/${result.data.id}`);
        return true;
      }
      toast(t("workbench.fork.failed"));
      return false;
    },
    [navigate, t],
  );

  return forkNet;
}
