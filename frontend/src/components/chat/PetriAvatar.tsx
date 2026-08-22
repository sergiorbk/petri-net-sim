import { cn } from "@/lib/utils";

interface PetriAvatarProps {
  isThinking: boolean;
}

// Diamond cycle: P1(top) → T1(right) → P2(bottom) → T2(left) → P1
const CYCLE_PATH = "M 10,3 L 17,10 L 10,17 L 3,10 Z";

export function PetriAvatar({ isThinking }: PetriAvatarProps) {
  return (
    <span
      className={cn(
        "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center",
        "rounded-full bg-gradient-to-br from-accent to-indigo-600",
      )}
      aria-hidden="true"
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
        {/* Arcs (shapes rendered on top) */}
        <line x1="10" y1="3"  x2="17" y2="10" stroke="white" strokeWidth="0.75" strokeOpacity="0.5" />
        <line x1="17" y1="10" x2="10" y2="17" stroke="white" strokeWidth="0.75" strokeOpacity="0.5" />
        <line x1="10" y1="17" x2="3"  y2="10" stroke="white" strokeWidth="0.75" strokeOpacity="0.5" />
        <line x1="3"  y1="10" x2="10" y2="3"  stroke="white" strokeWidth="0.75" strokeOpacity="0.5" />

        {/* Places */}
        <circle cx="10" cy="3"  r="2.5" stroke="white" strokeWidth="1" strokeOpacity="0.85" />
        <circle cx="10" cy="17" r="2.5" stroke="white" strokeWidth="1" strokeOpacity="0.85" />

        {/* Transitions */}
        <rect x="15.75" y="7.5" width="2.5" height="5" rx="0.5" stroke="white" strokeWidth="1" strokeOpacity="0.85" />
        <rect x="1.75"  y="7.5" width="2.5" height="5" rx="0.5" stroke="white" strokeWidth="1" strokeOpacity="0.85" />

        {/* Token — spinning when thinking, breathing when idle */}
        {isThinking ? (
          <circle r="2" fill="white">
            <animateMotion dur="1.5s" repeatCount="indefinite" path={CYCLE_PATH} />
          </circle>
        ) : (
          <circle cx="10" cy="3" r="2" fill="white">
            <animate attributeName="r"       values="1;3;1"     dur="2.8s" repeatCount="indefinite" />
            <animate attributeName="opacity" values="1;0.15;1"  dur="2.8s" repeatCount="indefinite" />
          </circle>
        )}
      </svg>
    </span>
  );
}
