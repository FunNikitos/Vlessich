/** Admin role badge — superadmin/support/readonly. */
import type { Role } from "@/lib/types";

const ROLE_TONE: Record<Role, string> = {
  superadmin: "bg-brand-green/20 text-brand-green border-brand-green/40",
  support: "bg-announcement/20 text-announcement border-announcement/40",
  readonly: "bg-bg-mid text-text-muted border-border-base/40",
};

export function RoleBadge({ role }: { role: Role }) {
  return (
    <span
      className={[
        "inline-flex items-center rounded-pill border px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-[1.4px]",
        ROLE_TONE[role],
      ].join(" ")}
    >
      {role}
    </span>
  );
}
