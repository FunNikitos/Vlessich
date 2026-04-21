/** Subscriptions list page: filters + revoke mutation. */
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  Card,
  ConfirmDestructiveModal,
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
import { api, ApiError } from "@/lib/api";
import type { SubscriptionAdminOut } from "@/lib/types";

const PAGE_LIMIT = 50;

export function SubscriptionsPage() {
  const { auth } = useAuth();
  const canRevoke = auth ? hasRole(auth.role, "support") : false;

  const [searchParams, setSearchParams] = useSearchParams();
  const initialUserId = searchParams.get("user_id") ?? "";

  const [status, setStatus] = useState<string>("");
  const [plan, setPlan] = useState<string>("");
  const [userIdInput, setUserIdInput] = useState<string>(initialUserId);
  const [page, setPage] = useState(1);
  const [revokeTarget, setRevokeTarget] =
    useState<SubscriptionAdminOut | null>(null);
  const [revokeErr, setRevokeErr] = useState<string | null>(null);
  const debouncedUserId = useDebounced(userIdInput, 400);

  const userIdParsed = useMemo<number | undefined>(() => {
    const trimmed = debouncedUserId.trim();
    if (!trimmed) return undefined;
    const n = Number(trimmed);
    return Number.isFinite(n) && Number.isInteger(n) && n > 0 ? n : undefined;
  }, [debouncedUserId]);

  const userIdInvalid =
    debouncedUserId.trim().length > 0 && userIdParsed === undefined;

  // Sync user_id → URL
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (userIdParsed) {
      next.set("user_id", String(userIdParsed));
    } else {
      next.delete("user_id");
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [userIdParsed, searchParams, setSearchParams]);

  const qc = useQueryClient();

  const revokeMut = useMutation({
    mutationFn: (id: string) => api.subscriptions.revoke(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["subs"] });
      qc.invalidateQueries({ queryKey: ["stats"] });
      setRevokeTarget(null);
      setRevokeErr(null);
    },
    onError: (err) => {
      setRevokeErr(err instanceof ApiError ? err.message : "Ошибка");
    },
  });

  const queryKey = useMemo(
    () =>
      ["subs", { status, plan, user_id: userIdParsed, page }] as const,
    [status, plan, userIdParsed, page],
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey,
    queryFn: () =>
      api.subscriptions.list({
        status: status || undefined,
        plan: plan || undefined,
        user_id: userIdParsed,
        page,
        limit: PAGE_LIMIT,
      }),
    enabled: !userIdInvalid,
  });

  const columns: Column<SubscriptionAdminOut>[] = [
    {
      key: "id",
      label: "ID",
      width: "110px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-muted">
          {r.id.slice(0, 8)}
        </span>
      ),
    },
    {
      key: "user",
      label: "User",
      width: "130px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-base">
          {r.user_id}
        </span>
      ),
    },
    { key: "plan", label: "Plan", width: "90px", render: (r) => r.plan },
    {
      key: "status",
      label: "Status",
      width: "110px",
      render: (r) => <StatusBadge status={r.status} />,
    },
    {
      key: "devices",
      label: "Dev",
      width: "60px",
      render: (r) => String(r.devices_limit),
    },
    {
      key: "started",
      label: "Started",
      width: "150px",
      render: (r) => new Date(r.started_at).toLocaleString("ru-RU"),
    },
    {
      key: "expires",
      label: "Expires",
      width: "150px",
      render: (r) =>
        r.expires_at ? (
          new Date(r.expires_at).toLocaleString("ru-RU")
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
  ];

  if (canRevoke) {
    columns.push({
      key: "actions",
      label: "",
      width: "110px",
      align: "right",
      render: (r) =>
        r.status === "ACTIVE" || r.status === "TRIAL" ? (
          <PillButton
            variant="danger"
            size="sm"
            onClick={(e) => {
              e.stopPropagation();
              setRevokeTarget(r);
              setRevokeErr(null);
            }}
          >
            Revoke
          </PillButton>
        ) : null,
    });
  }

  const total = data?.total ?? 0;

  return (
    <div>
      <PageHeading title="Subscriptions" subtitle={`Всего: ${total}`} />

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
              <option value="TRIAL">Trial</option>
              <option value="EXPIRED">Expired</option>
              <option value="REVOKED">Revoked</option>
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
          <FormField
            label="User TG ID"
            error={userIdInvalid ? "Положительное число" : undefined}
          >
            <Input
              inputMode="numeric"
              placeholder="tg_id"
              value={userIdInput}
              onChange={(e) => {
                setUserIdInput(e.target.value);
                setPage(1);
              }}
            />
          </FormField>
          <div className="flex items-end">
            <PillButton
              variant="ghost"
              size="sm"
              onClick={() => {
                setStatus("");
                setPlan("");
                setUserIdInput("");
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
        rows={data?.items ?? []}
        rowKey={(r) => r.id}
        loading={isLoading}
        empty="Подписок не найдено"
      />
      <Pagination
        page={page}
        total={total}
        limit={PAGE_LIMIT}
        onChange={setPage}
      />

      <ConfirmDestructiveModal
        open={revokeTarget !== null}
        onClose={() => {
          setRevokeTarget(null);
          setRevokeErr(null);
        }}
        onConfirm={() => {
          if (revokeTarget) revokeMut.mutate(revokeTarget.id);
        }}
        title="Revoke subscription"
        body={
          revokeTarget
            ? `Подписка ${revokeTarget.id.slice(0, 8)} (user ${revokeTarget.user_id}) будет помечена как REVOKED и expires_at=now. Это действие необратимо.`
            : ""
        }
        loading={revokeMut.isPending}
        error={revokeErr}
      />
    </div>
  );
}
