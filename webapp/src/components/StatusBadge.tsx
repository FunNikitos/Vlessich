type Status = "active" | "trial" | "expired" | "revoked" | "none";

const COLORS: Record<Status, string> = {
  active: "bg-brand-green text-black",
  trial: "bg-announcement text-black",
  expired: "bg-negative text-black",
  revoked: "bg-border-base text-text-base",
  none: "bg-bg-mid text-text-muted",
};

const LABELS: Record<Status, string> = {
  active: "Активна",
  trial: "Триал",
  expired: "Истекла",
  revoked: "Отозвана",
  none: "Нет подписки",
};

interface StatusBadgeProps {
  status: Status;
}

/** 10.5px uppercase pill badge per Design.txt §3 (Badge typography). */
export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      className={
        "inline-block rounded-pill px-2 py-1 text-[10.5px] font-semibold uppercase tracking-[1.4px] " +
        COLORS[status]
      }
    >
      {LABELS[status]}
    </span>
  );
}

/** Map backend status to badge prop. */
export function statusFromBackend(s: string | null | undefined): Status {
  if (s === "ACTIVE") return "active";
  if (s === "TRIAL") return "trial";
  if (s === "EXPIRED") return "expired";
  if (s === "REVOKED") return "revoked";
  return "none";
}
