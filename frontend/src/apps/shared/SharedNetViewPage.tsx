import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, LogIn } from "lucide-react";
import { getSharedNet } from "@/lib/nets-client";
import { useAuthStore } from "@/stores/auth-store";
import { useUserNetsStore } from "@/stores/user-nets-store";
import { useEditorStore } from "@/stores/editor-store";
import { useCanvasTabsStore } from "@/stores/canvas-tabs-store";
import { SimulatorApp } from "@/apps/simulator/SimulatorApp";
import { createUserNet } from "@/lib/nets-client";

export function SharedNetViewPage() {
  const { t } = useTranslation();
  const { shareToken } = useParams<{ shareToken: string }>();
  const navigate = useNavigate();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const addSharedNet = useUserNetsStore((s) => s.addSharedNet);

  const [netName, setNetName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [forking, setForking] = useState(false);
  const addedRef = useRef(false);

  useEffect(() => {
    if (!shareToken) return;
    getSharedNet(shareToken)
      .then((res) => {
        if (!res.ok) {
          setError(res.status === 404 ? t("shared.netNotFound") : t("shared.failedToLoad"));
          return;
        }
        const net = res.data;
        setNetName(net.name);
        // A different document is entering the editor; canvases opened on the
        // previous one must not carry over into the shared view.
        useCanvasTabsStore.getState().resetToRoot();
        useEditorStore.getState().setNet(net.net_data);
        useEditorStore.setState({ cloudNetId: null });
        setReady(true);
      })
      .catch(() => setError(t("shared.failedToLoad")));
  }, [shareToken, t]);

  useEffect(() => {
    if (!isAuthenticated || !shareToken || !ready || addedRef.current) return;
    addedRef.current = true;
    addSharedNet(shareToken);
  }, [isAuthenticated, shareToken, ready, addSharedNet]);

  async function handleOpenInEditor() {
    if (!shareToken) return;
    setForking(true);
    try {
      const res = await getSharedNet(shareToken);
      if (!res.ok) return;
      const result = await createUserNet({ name: res.data.name, net_data: res.data.net_data });
      if (result.ok) navigate(`/nets/${result.data.id}`);
    } finally {
      setForking(false);
    }
  }

  if (error) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-sm text-text-secondary">{error}</p>
        <button
          type="button"
          className="text-sm text-accent hover:underline"
          onClick={() => navigate("/nets")}
        >
          {t("shared.goToGallery")}
        </button>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-secondary">
        {t("common.loading")}
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-9 shrink-0 items-center gap-2 border-b border-border bg-surface-secondary px-3">
        <button
          type="button"
          className="rounded p-1 text-text-secondary hover:bg-surface-hover hover:text-text-primary"
          onClick={() => navigate(-1)}
          aria-label="Back"
        >
          <ArrowLeft size={14} />
        </button>

        <span className="flex-1 truncate text-sm font-medium text-text-primary">
          {netName}
        </span>

        {isAuthenticated ? (
          <button
            type="button"
            disabled={forking}
            onClick={handleOpenInEditor}
            className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {forking ? t("shared.opening") : t("shared.openInEditor")}
          </button>
        ) : (
          <Link
            to="/login"
            className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1 text-xs text-text-secondary hover:bg-surface-hover hover:text-text-primary"
          >
            <LogIn size={12} />
            {t("shared.signInToEdit")}
          </Link>
        )}
      </header>

      <div className="min-h-0 flex-1">
        <SimulatorApp readOnly />
      </div>
    </div>
  );
}
