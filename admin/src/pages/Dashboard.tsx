/** Admin dashboard: node health panel + metric cards. */
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  PageHeading,
  PillButton,
  SkeletonBlock,
} from "@/components";
import { api } from "@/lib/api";
import type { StatsOut } from "@/lib/types";

export function DashboardPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["stats"],
    queryFn: () => api.stats(),
    refetchInterval: 30000,
  });

  return (
    <div>
      <PageHeading
        title="Dashboard"
        subtitle="Сводка по системе · auto-refresh 30s"
      />

      {isError && (
        <Card padded className="mb-4 border border-negative/40">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-negative">
              Ошибка загрузки: {(error as Error).message}
            </p>
            <PillButton variant="ghost" size="sm" onClick={() => refetch()}>
              Retry
            </PillButton>
          </div>
        </Card>
      )}

      <NodeHealthPanel stats={data} loading={isLoading} />

      <section className="mt-6">
        <h2 className="mb-3 text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted">
          Stats
        </h2>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          <MetricCard
            label="Users total"
            value={data?.users_total}
            loading={isLoading}
          />
          <MetricCard
            label="Subs active"
            value={data?.subs_active}
            loading={isLoading}
          />
          <MetricCard
            label="Subs trial"
            value={data?.subs_trial}
            loading={isLoading}
          />
          <MetricCard
            label="Codes unused / total"
            value={
              data
                ? `${data.codes_unused} / ${data.codes_total}`
                : undefined
            }
            loading={isLoading}
          />
          <MetricCard
            label="Nodes healthy / total"
            value={
              data
                ? `${data.nodes_healthy} / ${data.nodes_total}`
                : undefined
            }
            loading={isLoading}
          />
          <MetricCard
            label="Nodes burned"
            value={data?.nodes_burned}
            loading={isLoading}
            tone={
              data && data.nodes_burned > 0 ? "danger" : "neutral"
            }
          />
        </div>
      </section>
    </div>
  );
}

function MetricCard({
  label,
  value,
  loading,
  tone = "neutral",
}: {
  label: string;
  value: string | number | undefined;
  loading?: boolean;
  tone?: "neutral" | "danger";
}) {
  const valueCls =
    tone === "danger" ? "text-negative" : "text-text-base";
  return (
    <Card padded>
      <div className="text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted">
        {label}
      </div>
      <div className={`mt-2 font-title text-[28px] font-bold ${valueCls}`}>
        {loading ? (
          <SkeletonBlock height="2rem" width="6rem" />
        ) : value !== undefined ? (
          value
        ) : (
          "—"
        )}
      </div>
    </Card>
  );
}

function NodeHealthPanel({
  stats,
  loading,
}: {
  stats: StatsOut | undefined;
  loading: boolean;
}) {
  const total = stats?.nodes_total ?? 0;
  const healthy = stats?.nodes_healthy ?? 0;
  const burned = stats?.nodes_burned ?? 0;
  const maintenance = stats?.nodes_maintenance ?? 0;
  const stale = stats?.nodes_stale ?? 0;

  const pct = (n: number) => (total > 0 ? (n / total) * 100 : 0);

  return (
    <section>
      <h2 className="mb-3 text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted">
        Node health
      </h2>
      <Card padded>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Tile
            label="Total"
            value={total}
            loading={loading}
            accent="text-text-base"
          />
          <Tile
            label="Healthy"
            value={healthy}
            loading={loading}
            accent="text-brand-green"
          />
          <Tile
            label="Burned"
            value={burned}
            loading={loading}
            accent="text-negative"
          />
          <Tile
            label="Maintenance"
            value={maintenance}
            loading={loading}
            accent="text-warning"
          />
          <Tile
            label="Stale"
            value={stale}
            loading={loading}
            accent="text-warning"
          />
        </div>

        <div className="mt-4">
          {loading ? (
            <SkeletonBlock height="12px" />
          ) : total === 0 ? (
            <p className="text-xs text-text-muted">Нет нод.</p>
          ) : (
            <div
              className="flex h-3 w-full overflow-hidden rounded-pill bg-bg-mid"
              role="img"
              aria-label="Node health distribution"
            >
              {healthy > 0 && (
                <div
                  style={{ width: `${pct(healthy)}%` }}
                  className="bg-brand-green"
                  title={`Healthy: ${healthy}`}
                />
              )}
              {maintenance > 0 && (
                <div
                  style={{ width: `${pct(maintenance)}%` }}
                  className="bg-warning"
                  title={`Maintenance: ${maintenance}`}
                />
              )}
              {stale > 0 && (
                <div
                  style={{ width: `${pct(stale)}%` }}
                  className="bg-warning/60"
                  title={`Stale: ${stale}`}
                />
              )}
              {burned > 0 && (
                <div
                  style={{ width: `${pct(burned)}%` }}
                  className="bg-negative"
                  title={`Burned: ${burned}`}
                />
              )}
            </div>
          )}
        </div>
      </Card>
    </section>
  );
}

function Tile({
  label,
  value,
  loading,
  accent,
}: {
  label: string;
  value: number;
  loading: boolean;
  accent: string;
}) {
  return (
    <div className="rounded-md bg-bg-mid p-3">
      <div className="text-[10px] font-bold uppercase tracking-[1.6px] text-text-muted">
        {label}
      </div>
      <div className={`mt-1 font-title text-[22px] font-bold ${accent}`}>
        {loading ? <SkeletonBlock height="1.5rem" width="3rem" /> : value}
      </div>
    </div>
  );
}
