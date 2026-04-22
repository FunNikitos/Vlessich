/** Shimmer skeleton block. */
export interface SkeletonBlockProps {
  width?: string;
  height?: string;
  className?: string;
}

export function SkeletonBlock({
  width = "100%",
  height = "1rem",
  className,
}: SkeletonBlockProps) {
  return (
    <div
      className={["animate-pulse rounded bg-bg-mid", className ?? ""].join(" ")}
      style={{ width, height }}
    />
  );
}
