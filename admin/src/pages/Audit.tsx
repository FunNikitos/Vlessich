/** Audit log page: filters, expandable rows with full payload. */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  FormField,
  Input,
  PageHeading,
  Pagination,
  PillButton,
  Select,
  Table,
} from "@/components";
import type { Column } from "@/components";
import { useDebounced } from "@/hooks/useDebounced";
import { api } from "@/lib/api";
import type { AuditOut } from "@/lib/types";

const PAGE_LIMIT = 50;

export function AuditPage() {
  const [action, setAction] = useState("");
  const [actorType, setActorType] = useState("");
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const debouncedAction = useDebounced(action, 400);

  const queryKey = useMemo(
    () =>
      [
        "audit",
        { action: debouncedAction, actor_type: actorType, page },
      ] as const,
    [debouncedAction, actorType, page],
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey,
    queryFn: () =>
      api.audit.list({
        action: debouncedAction || undefined,
        actor_type: actorType || undefined,
        page,
        limit: PAGE_LIMIT,
      }),
  });

  function toggleExpand(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const columns: Column<AuditOut>[] = [
    {
      key: "at",
      label: "Time",
      width: "170px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-base">
          {new Date(r.at).toLocaleString("ru-RU")}
        </span>
      ),
    },
    {
      key: "actor",
      label: "Actor",
      width: "150px",
      render: (r) => (
        <span className="text-text-muted">
          {r.actor_type}
          {r.actor_ref ? `:${r.actor_ref}` : ""}
        </span>
      ),
    },
    {
      key: "action",
      label: "Action",
      width: "200px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-base">{r.action}</span>
      ),
    },
    {
      key: "target",
      label: "Target",
      render: (r) =>
        r.target_type ? (
          <span className="text-text-muted">
            {r.target_type}
            {r.target_id ? `:${r.target_id.slice(0, 12)}` : ""}
          </span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "expand",
      label: "",
      width: "80px",
      align: "right",
      render: (r) => (
        <PillButton
          variant="ghost"
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            toggleExpand(r.id);
          }}
        >
          {expanded.has(r.id) ? "Hide" : "JSON"}
        </PillButton>
      ),
    },
  ];

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div>
      <PageHeading title="Audit" subtitle={`Всего: ${total}`} />

      <Card padded className="mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <FormField label="Action">
            <Input
              placeholder="например, code.revoke"
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                setPage(1);
              }}
            />
          </FormField>
          <FormField label="Actor type">
            <Select
              value={actorType}
              onChange={(e) => {
                setActorType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All</option>
              <option value="admin">admin</option>
              <option value="system">system</option>
              <option value="user">user</option>
              <option value="bot">bot</option>
            </Select>
          </FormField>
          <div className="flex items-end">
            <PillButton
              variant="ghost"
              size="sm"
              onClick={() => {
                setAction("");
                setActorType("");
                setPage(1);
              }}
            >
              Reset
            </PillButton>
          </div>
        </div>
      </Card>

      {isError && (
        <Card className="mb-4 border border-negative/40">
          <p className="text-sm text-negative">
            Ошибка загрузки: {(error as Error).message}
          </p>
        </Card>
      )}

      <Table
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        loading={isLoading}
        empty="Записей не найдено"
      />

      {/* Expanded payloads (rendered separately to keep Table generic) */}
      {rows
        .filter((r) => expanded.has(r.id))
        .map((r) => (
          <Card key={r.id} padded className="mt-2 border border-border-base/40">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[10.5px] font-bold uppercase tracking-[1.8px] text-text-muted">
                {r.action} · {r.id.slice(0, 8)}
              </span>
              <PillButton
                variant="ghost"
                size="sm"
                onClick={() => toggleExpand(r.id)}
              >
                Hide
              </PillButton>
            </div>
            <pre className="max-h-[320px] overflow-auto rounded-md bg-bg-mid p-3 font-mono text-[11.5px] leading-relaxed text-text-base">
              {JSON.stringify(r, null, 2)}
            </pre>
          </Card>
        ))}

      <Pagination
        page={page}
        total={total}
        limit={PAGE_LIMIT}
        onChange={setPage}
      />
    </div>
  );
}
