/** Codes list page: filters, pagination, RBAC revoke. */
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
  StatusBadge,
  Table,
} from "@/components";
import type { Column } from "@/components";
import { useAuth } from "@/hooks/useAuth";
import { useDebounced } from "@/hooks/useDebounced";
import { hasRole } from "@/lib/auth";
import { api } from "@/lib/api";
import type { CodeOut } from "@/lib/types";

const PAGE_LIMIT = 50;

export function CodesPage() {
  const { auth } = useAuth();
  const canWrite = auth ? hasRole(auth.role, "support") : false;
  const canRevoke = auth ? hasRole(auth.role, "superadmin") : false;

  const [status, setStatus] = useState<string>("");
  const [plan, setPlan] = useState<string>("");
  const [tag, setTag] = useState<string>("");
  const [page, setPage] = useState(1);
  const debouncedTag = useDebounced(tag, 400);

  const queryKey = useMemo(
    () => ["codes", { status, plan, tag: debouncedTag, page }] as const,
    [status, plan, debouncedTag, page],
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey,
    queryFn: () =>
      api.codes.list({
        status: status || undefined,
        plan: plan || undefined,
        page,
        limit: PAGE_LIMIT,
      }),
  });

  const columns: Column<CodeOut>[] = [
    {
      key: "id",
      label: "ID",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-muted">
          {r.id.slice(0, 8)}
        </span>
      ),
      width: "110px",
    },
    { key: "plan", label: "Plan", render: (r) => r.plan_name, width: "90px" },
    {
      key: "dur",
      label: "Dur",
      render: (r) => `${r.duration_days}d`,
      width: "72px",
    },
    {
      key: "dev",
      label: "Dev",
      render: (r) => String(r.devices_limit),
      width: "60px",
    },
    {
      key: "status",
      label: "Status",
      render: (r) => <StatusBadge status={r.status} />,
      width: "100px",
    },
    {
      key: "tag",
      label: "Tag",
      render: (r) =>
        r.tag ? (
          <span className="text-text-muted">{r.tag}</span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "created",
      label: "Created",
      render: (r) => new Date(r.created_at).toLocaleString("ru-RU"),
      width: "140px",
    },
  ];

  if (canRevoke) {
    columns.push({
      key: "actions",
      label: "",
      width: "110px",
      align: "right",
      render: (r) =>
        r.status === "ACTIVE" ? (
          <PillButton variant="danger" size="sm" disabled>
            Revoke
          </PillButton>
        ) : null,
    });
  }

  // Client-side tag filter: backend /admin/codes currently lacks `tag` param.
  const rows = useMemo(() => {
    if (!data) return [];
    const needle = debouncedTag.trim().toLowerCase();
    if (!needle) return data.items;
    return data.items.filter((c) => (c.tag ?? "").toLowerCase().includes(needle));
  }, [data, debouncedTag]);

  const total = data?.total ?? 0;

  return (
    <div>
      <PageHeading
        title="Codes"
        subtitle={`Всего: ${total}`}
        action={
          <PillButton variant="primary" disabled={!canWrite}>
            + Create batch
          </PillButton>
        }
      />

      <Card padded className="mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <FormField label="Status">
            <Select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All</option>
              <option value="ACTIVE">Active</option>
              <option value="USED">Used</option>
              <option value="REVOKED">Revoked</option>
              <option value="EXPIRED">Expired</option>
            </Select>
          </FormField>
          <FormField label="Plan">
            <Select
              value={plan}
              onChange={(e) => {
                setPlan(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All</option>
              <option value="7d">7 дней</option>
              <option value="1m">1 месяц</option>
              <option value="3m">3 месяца</option>
              <option value="6m">6 месяцев</option>
              <option value="1y">Год</option>
            </Select>
          </FormField>
          <FormField label="Tag">
            <Input
              placeholder="поиск по тегу"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
            />
          </FormField>
          <div className="flex items-end">
            <PillButton
              variant="ghost"
              size="sm"
              onClick={() => {
                setStatus("");
                setPlan("");
                setTag("");
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
        empty="Кодов не найдено"
      />
      <Pagination
        page={page}
        total={total}
        limit={PAGE_LIMIT}
        onChange={setPage}
      />
    </div>
  );
}
