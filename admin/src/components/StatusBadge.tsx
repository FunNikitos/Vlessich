/** Status pill badge — subscription/code/node states. */
import type { ReactNode } from "react";

type Tone = "success" | "warning" | "danger" | "info" | "neutral";

const TONE_CLS: Record<Tone, string> = {
  success: "bg-brand-green/15 text-brand-green border-brand-green/30",
  warning: "bg-warning/15 text-warning border-warning/40",
  danger: "bg-negative/15 text-negative border-negative/40",
  info: "bg-announcement/15 text-announcement border-announcement/40",
  neutral: "bg-bg-mid text-text-muted border-border-base/40",
};

const STATUS_TONE: Record<string, Tone> = {
  ACTIVE: "success",
  HEALTHY: "success",
  TRIAL: "info",
  EXPIRED: "neutral",
  REVOKED: "danger",
  BURNED: "danger",
  MAINTENANCE: "warning",
  DISABLED: "neutral",
  USED: "neutral",
  STALE: "warning",
};

export interface StatusBadgeProps {
  status: string;
  tone?: Tone;
  children?: ReactNode;
}

export function StatusBadge({ status, tone, children }: StatusBadgeProps) {
  const t = tone ?? STATUS_TONE[status.toUpperCase()] ?? "neutral";
  return (
    <span
      className={[
        "inline-flex items-center rounded-pill border px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-[1.4px]",
        TONE_CLS[t],
      ].join(" ")}
    >
      {children ?? status}
    </span>
  );
}
