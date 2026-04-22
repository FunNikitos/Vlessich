/** Spotify-dark card: elevated #181818 bg, 8px radius, optional title. */
import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  title?: ReactNode;
  action?: ReactNode;
  padded?: boolean;
}

export function Card({
  title,
  action,
  padded = true,
  children,
  className,
  ...rest
}: CardProps) {
  const cls = [
    "rounded-lg bg-bg-elevated shadow-[0_8px_8px_rgba(0,0,0,0.3)]",
    padded ? "p-5" : "",
    className ?? "",
  ].join(" ");
  return (
    <div className={cls} {...rest}>
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between">
          {title ? (
            <h2 className="font-title text-[11px] font-bold uppercase tracking-[2px] text-text-muted">
              {title}
            </h2>
          ) : (
            <span />
          )}
          {action}
        </div>
      )}
      {children}
    </div>
  );
}
