/** Nodes list page: create/edit (superadmin), health drawer. */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  CreateNodeModal,
  EditNodeModal,
  NodeHealthDrawer,
  PageHeading,
  PillButton,
  StatusBadge,
  Table,
} from "@/components";
import type { Column } from "@/components";
import { useAuth } from "@/hooks/useAuth";
import { hasRole } from "@/lib/auth";
import { api } from "@/lib/api";
import type { NodeOut } from "@/lib/types";

export function NodesPage() {
  const { auth } = useAuth();
  const canWrite = auth ? hasRole(auth.role, "superadmin") : false;

  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<NodeOut | null>(null);
  const [healthTarget, setHealthTarget] = useState<NodeOut | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["nodes"],
    queryFn: () => api.nodes.list(),
    refetchInterval: 30000,
  });

  const columns: Column<NodeOut>[] = [
    {
      key: "host",
      label: "Hostname",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-base">
          {r.hostname}
        </span>
      ),
    },
    {
      key: "ip",
      label: "Current IP",
      width: "140px",
      render: (r) =>
        r.current_ip ? (
          <span className="font-mono text-[12px] text-text-muted">
            {r.current_ip}
          </span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "provider",
      label: "Provider",
      width: "110px",
      render: (r) =>
        r.provider ? (
          <span className="text-text-muted">{r.provider}</span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "region",
      label: "Region",
      width: "100px",
      render: (r) =>
        r.region ? (
          <span className="text-text-muted">{r.region}</span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "status",
      label: "Status",
      width: "120px",
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: "last_probe",
      label: "Last probe",
      width: "160px",
      render: (r) =>
        r.last_probe_at ? (
          new Date(r.last_probe_at).toLocaleString("ru-RU")
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "actions",
      label: "",
      width: "200px",
      align: "right",
      render: (r) => (
        <div className="flex justify-end gap-2">
          <PillButton
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              setHealthTarget(r);
            }}
          >
            Health
          </PillButton>
          {canWrite && (
            <PillButton
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                setEditTarget(r);
              }}
            >
              Edit
            </PillButton>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeading
        title="Nodes"
        subtitle={`Всего: ${data?.length ?? 0}`}
        action={
          <PillButton
            variant="primary"
            disabled={!canWrite}
            onClick={() => setCreateOpen(true)}
          >
            + Create node
          </PillButton>
        }
      />

      {isError && (
        <Card className="mb-4 border border-negative/40">
          <p className="text-sm text-negative">
            Ошибка загрузки: {(error as Error).message}
          </p>
        </Card>
      )}

      <Table
        columns={columns}
        rows={data ?? []}
        rowKey={(r) => r.id}
        loading={isLoading}
        empty="Нод не найдено"
        onRowClick={(r) => setHealthTarget(r)}
      />

      <CreateNodeModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
      />
      <EditNodeModal node={editTarget} onClose={() => setEditTarget(null)} />
      <NodeHealthDrawer
        node={healthTarget}
        onClose={() => setHealthTarget(null)}
      />
    </div>
  );
}
