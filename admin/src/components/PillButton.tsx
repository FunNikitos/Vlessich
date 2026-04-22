/** Primary CTA / secondary / ghost / danger pill button.
 * Spotify-dark: uppercase + letter-spacing, pill radius, strict palette.
 */
import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

export interface PillButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leadingIcon?: ReactNode;
}

const SIZE_CLS: Record<Size, string> = {
  sm: "px-3.5 py-1.5 text-[11px] tracking-[1.6px]",
  md: "px-5 py-2.5 text-[13px] tracking-[1.6px]",
  lg: "px-7 py-3 text-[14px] tracking-[1.8px]",
};

const VARIANT_CLS: Record<Variant, string> = {
  primary:
    "bg-brand-green text-black hover:bg-[#1fdf6c] active:scale-[0.97] disabled:bg-brand-green/50",
  secondary:
    "bg-bg-mid text-text-base hover:bg-[#2a2a2a] active:scale-[0.97]",
  ghost:
    "border border-border-muted text-text-base hover:border-text-base active:scale-[0.97]",
  danger:
    "bg-negative/20 text-negative border border-negative/60 hover:bg-negative/30 active:scale-[0.97]",
};

export const PillButton = forwardRef<HTMLButtonElement, PillButtonProps>(
  function PillButton(
    {
      variant = "primary",
      size = "md",
      loading = false,
      leadingIcon,
      disabled,
      children,
      className,
      ...rest
    },
    ref,
  ) {
    const cls = [
      "inline-flex items-center justify-center gap-2 rounded-pill font-bold uppercase transition disabled:cursor-not-allowed disabled:opacity-60",
      SIZE_CLS[size],
      VARIANT_CLS[variant],
      className ?? "",
    ].join(" ");
    return (
      <button
        ref={ref}
        type={rest.type ?? "button"}
        disabled={disabled || loading}
        className={cls}
        {...rest}
      >
        {loading ? <Spinner /> : leadingIcon}
        <span>{children}</span>
      </button>
    );
  },
);

function Spinner() {
  return (
    <span
      aria-hidden
      className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
    />
  );
}
