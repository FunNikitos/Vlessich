/** Page heading. */
import type { ReactNode } from "react";

export function PageHeading({
  title,
  action,
  subtitle,
}: {
  title: string;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex items-start justify-between gap-4">
      <div>
        <h1 className="font-title text-[22px] font-bold uppercase tracking-[2px] text-text-base">
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm text-text-muted">{subtitle}</p>
        )}
      </div>
      {action}
    </header>
  );
}
