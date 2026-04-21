import type { HTMLAttributes, ReactNode } from "react";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  elevated?: boolean;
}

/** Spotify-dark card: #181818 surface, 8px radius, optional heavy shadow. */
export function Card({
  children,
  elevated = false,
  className = "",
  ...rest
}: CardProps) {
  return (
    <div
      {...rest}
      className={
        "rounded-lg bg-bg-elevated p-5 " +
        (elevated ? "shadow-elevated " : "") +
        className
      }
    >
      {children}
    </div>
  );
}
