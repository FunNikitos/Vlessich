/** Generic admin table. #181818 header, #121212 body, hover #1f1f1f. */
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  width?: string;
  align?: "left" | "right" | "center";
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  loading,
  empty,
  onRowClick,
}: TableProps<T>) {
  return (
    <div className="overflow-hidden rounded-lg border border-border-base/40">
      <table className="w-full border-collapse text-left">
        <thead className="bg-bg-elevated">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                className="px-3 py-2.5 text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted"
                style={{ width: c.width, textAlign: c.align ?? "left" }}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="bg-bg-base">
          {loading ? (
            <SkeletonRows columns={columns.length} />
          ) : rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-8 text-center text-sm text-text-muted"
              >
                {empty ?? "Нет данных"}
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr
                key={rowKey(r)}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                className={[
                  "border-t border-border-base/30 text-sm text-text-base",
                  onRowClick
                    ? "cursor-pointer hover:bg-bg-mid"
                    : "hover:bg-bg-mid/50",
                ].join(" ")}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className="px-3 py-2.5"
                    style={{ textAlign: c.align ?? "left" }}
                  >
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

function SkeletonRows({ columns }: { columns: number }) {
  return (
    <>
      {Array.from({ length: 5 }).map((_, i) => (
        <tr key={i} className="border-t border-border-base/30">
          {Array.from({ length: columns }).map((__, j) => (
            <td key={j} className="px-3 py-3">
              <div className="h-3.5 w-24 animate-pulse rounded bg-bg-mid" />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
