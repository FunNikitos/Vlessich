interface SkeletonProps {
  width?: string;
  height?: string;
  radius?: string;
  className?: string;
}

/** Shimmer placeholder block. CSS-only animation, no JS. */
export function SkeletonBlock({
  width = "100%",
  height = "1rem",
  radius = "8px",
  className = "",
}: SkeletonProps) {
  return (
    <div
      className={"relative overflow-hidden bg-bg-mid " + className}
      style={{ width, height, borderRadius: radius }}
    >
      <span className="absolute inset-0 animate-[shimmer_1.5s_infinite] bg-gradient-to-r from-transparent via-white/5 to-transparent" />
    </div>
  );
}
