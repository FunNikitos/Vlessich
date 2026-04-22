import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md" | "lg";

interface PillButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  children: ReactNode;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary:
    "bg-brand-green text-black hover:bg-[#1fdf6c] active:scale-[0.97]",
  secondary:
    "bg-bg-mid text-text-base hover:bg-[#2a2a2a] active:scale-[0.97]",
  ghost:
    "bg-transparent text-text-base border border-border-muted hover:border-text-base",
};

const SIZE_CLASSES: Record<Size, string> = {
  sm: "px-4 py-2 text-xs tracking-[1.4px]",
  md: "px-6 py-3 text-sm tracking-[1.4px]",
  lg: "px-8 py-4 text-base tracking-[2px]",
};

/** Spotify-pill button: uppercase, tight tracking, 9999px radius. */
export function PillButton({
  variant = "primary",
  size = "md",
  loading = false,
  disabled,
  className = "",
  children,
  ...rest
}: PillButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <button
      {...rest}
      disabled={isDisabled}
      className={
        "inline-flex items-center justify-center rounded-pill font-bold uppercase transition-transform disabled:opacity-50 disabled:cursor-not-allowed " +
        VARIANT_CLASSES[variant] +
        " " +
        SIZE_CLASSES[size] +
        " " +
        className
      }
    >
      {loading ? (
        <span
          className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-label="loading"
        />
      ) : (
        children
      )}
    </button>
  );
}
