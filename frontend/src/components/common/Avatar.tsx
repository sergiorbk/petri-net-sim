import { cn } from "@/lib/utils";

interface AvatarProps {
  name: string;
  src?: string;
  size?: "sm" | "md";
  className?: string;
}

const sizeStyles = {
  sm: "h-7 w-7 text-xs",
  md: "h-9 w-9 text-sm",
};

function getInitials(name: string): string {
  return name
    .split(" ")
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
}

export function Avatar({ name, src, size = "md", className }: AvatarProps) {
  const initials = getInitials(name);

  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full",
        "bg-accent font-medium text-white select-none",
        sizeStyles[size],
        className,
      )}
      aria-hidden="true"
    >
      {src ? (
        <img
          src={src}
          alt=""
          className="h-full w-full rounded-full object-cover"
        />
      ) : (
        initials
      )}
    </span>
  );
}
