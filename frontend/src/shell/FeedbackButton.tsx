import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Bug, LifeBuoy, Lightbulb, MessageCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { DropdownMenu } from "@/components/common/DropdownMenu";
import { type IssueKind, issueLink } from "@/lib/github-issue-link";

/**
 * Bug reports, ideas and feedback, filed as GitHub issues in a new tab. Shown
 * signed in or not: a stranger trying the demo is exactly who should be able
 * to say what broke. Each label ends in "(GitHub)" so it is clear the report
 * leaves the app, and an in-app channel can join the menu later as its own item.
 */
export function FeedbackButton() {
  const { t } = useTranslation();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [menuAt, setMenuAt] = useState<{ x: number; y: number } | null>(null);

  const open = (kind: IssueKind) =>
    window.open(issueLink(kind), "_blank", "noopener,noreferrer");

  const toggle = () => {
    if (menuAt) {
      setMenuAt(null);
      return;
    }
    // The bar sits on the left edge, low on the screen: open to the right of
    // the button and let the menu's own clamping lift it above the bottom.
    const rect = buttonRef.current?.getBoundingClientRect();
    if (rect) setMenuAt({ x: rect.right + 4, y: rect.top });
  };

  const label = t("feedback.title");

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={toggle}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={menuAt !== null}
        title={label}
        className={cn(
          "flex h-10 w-10 items-center justify-center rounded-lg",
          "transition-colors focus-visible:outline-2",
          "focus-visible:outline-offset-2 focus-visible:outline-accent",
          menuAt
            ? "bg-sidebar-hover text-text-primary"
            : "text-text-muted hover:bg-sidebar-hover hover:text-text-primary",
        )}
      >
        <LifeBuoy size={20} />
      </button>
      <DropdownMenu
        open={menuAt !== null}
        onClose={() => setMenuAt(null)}
        position={menuAt}
        items={[
          {
            key: "bug",
            label: t("feedback.bug"),
            icon: <Bug size={16} />,
            onClick: () => open("bug"),
          },
          {
            key: "feature",
            label: t("feedback.feature"),
            icon: <Lightbulb size={16} />,
            onClick: () => open("feature"),
          },
          {
            key: "feedback",
            label: t("feedback.feedback"),
            icon: <MessageCircle size={16} />,
            onClick: () => open("feedback"),
          },
        ]}
      />
    </>
  );
}
