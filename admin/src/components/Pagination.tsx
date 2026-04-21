/** Pill-button pagination. Centered ellipsis on wide ranges. */
import { PillButton } from "./PillButton";

export interface PaginationProps {
  page: number;
  total: number;
  limit: number;
  onChange: (page: number) => void;
}

function buildPages(page: number, pages: number): (number | "…")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const set = new Set<number>([1, pages, page, page - 1, page + 1]);
  const arr = [...set].filter((p) => p >= 1 && p <= pages).sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  for (let i = 0; i < arr.length; i++) {
    if (i > 0 && arr[i] - arr[i - 1] > 1) out.push("…");
    out.push(arr[i]);
  }
  return out;
}

export function Pagination({ page, total, limit, onChange }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / limit));
  if (pages <= 1) return null;
  const items = buildPages(page, pages);
  return (
    <nav className="flex items-center justify-center gap-1.5 py-3">
      <PillButton
        variant="ghost"
        size="sm"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        «
      </PillButton>
      {items.map((p, idx) =>
        p === "…" ? (
          <span
            key={`gap-${idx}`}
            className="px-2 text-sm text-text-muted"
          >
            …
          </span>
        ) : (
          <PillButton
            key={p}
            variant={p === page ? "primary" : "secondary"}
            size="sm"
            onClick={() => onChange(p)}
          >
            {String(p)}
          </PillButton>
        ),
      )}
      <PillButton
        variant="ghost"
        size="sm"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        »
      </PillButton>
    </nav>
  );
}
