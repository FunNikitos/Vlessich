/** Node health drawer: uptime 24h, p50/p95, recent probes sparkline + table. */
import { useQuery } from "@tanstack/react-query";
import {
  Drawer,
  SkeletonBlock,
  Sparkline,
  StatusBadge,
} from "@/components";
import { api } from "@/lib/api";
import type { NodeOut } from "@/lib/types";

interface Props {
  node: NodeOut | null;
  onClose: () => void;
}

export function NodeHealthDrawer({ node, onClose }: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["node-health", node?.id],
    queryFn: () => api.nodes.health(node!.id),
    enabled: node !== null,
    refetchInterval: node !== null ? 15000 : false,
  });

  return (
    <Drawer
      open={node !== null}
      onClose={onClose}
      title={node ? `Health · ${node.hostname}` : ""}
    >
      {isLoading && (
        <div className="space-y-3">
          <SkeletonBlock height="56px" />
          <SkeletonBlock height="120px" />
          <SkeletonBlock height="200px" />
        </div>
      )}
      {isError && (
        <p className="text-sm text-negative">
          Ошибка загрузки: {(error as Error).message}
        </p>
      )}
      {data && (
        <div className="space-y-5">
          <div className="flex items-center gap-3">
            <StatusBadge status={data.status} />
            {data.last_probe_at && (
              <span className="text-[11px] text-text-muted">
                last probe:{" "}
                {new Date(data.last_probe_at).toLocaleString("ru-RU")}
              </span>
            )}
          </div>

          <div className="grid grid-cols-3 gap-3">
            <Stat label="Uptime 24h" value={fmtPct(data.uptime_24h_pct)} />
            <Stat label="p50" value={fmtMs(data.latency_p50_ms)} />
            <Stat label="p95" value={fmtMs(data.latency_p95_ms)} />
          </div>

          <section>
            <h4 className="mb-2 text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted">
              Recent probes ({data.recent_probes.length})
            </h4>
            <Sparkline probes={data.recent_probes} width={480} height={64} />
          </section>

          <section>
            <h4 className="mb-2 text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted">
              Probe log
            </h4>
            <div className="max-h-[260px] overflow-y-auto rounded-md border border-border-base/40">
              <table className="w-full text-left text-[12px]">
                <thead className="sticky top-0 bg-bg-elevated">
                  <tr>
                    <th className="px-3 py-1.5 text-text-muted">Time</th>
                    <th className="px-3 py-1.5 text-text-muted">OK</th>
                    <th className="px-3 py-1.5 text-text-muted">Latency</th>
                    <th className="px-3 py-1.5 text-text-muted">Error</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_probes.map((p, i) => (
                    <tr
                      key={`${p.probed_at}-${i}`}
                      className="border-t border-border-base/30"
                    >
                      <td className="px-3 py-1.5 font-mono text-text-base">
                        {new Date(p.probed_at).toLocaleTimeString("ru-RU")}
                      </td>
                      <td className="px-3 py-1.5">
                        {p.ok ? (
                          <span className="text-brand-green">●</span>
                        ) : (
                          <span className="text-negative">●</span>
                        )}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-text-base">
                        {p.latency_ms ?? "—"}
                      </td>
                      <td className="px-3 py-1.5 text-text-muted">
                        {p.error ?? ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </Drawer>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-bg-mid p-3">
      <div className="text-[10px] font-bold uppercase tracking-[1.6px] text-text-muted">
        {label}
      </div>
      <div className="mt-1 font-title text-lg text-text-base">{value}</div>
    </div>
  );
}

function fmtPct(v: number | null): string {
  if (v === null) return "—";
  return `${v.toFixed(1)}%`;
}

function fmtMs(v: number | null): string {
  if (v === null) return "—";
  return `${v} ms`;
}
