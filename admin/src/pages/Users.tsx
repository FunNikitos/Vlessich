/** Users list page: filter by tg_id, link to subscriptions. */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Card,
  FormField,
  Input,
  PageHeading,
  Pagination,
  PillButton,
  StatusBadge,
  Table,
} from "@/components";
import type { Column } from "@/components";
import { useDebounced } from "@/hooks/useDebounced";
import { api } from "@/lib/api";
import type { UserOut } from "@/lib/types";

const PAGE_LIMIT = 50;

export function UsersPage() {
  const [tgIdInput, setTgIdInput] = useState<string>("");
  const [page, setPage] = useState(1);
  const debouncedTgId = useDebounced(tgIdInput, 400);

  const tgIdParsed = useMemo<number | undefined>(() => {
    const trimmed = debouncedTgId.trim();
    if (!trimmed) return undefined;
    const n = Number(trimmed);
    return Number.isFinite(n) && Number.isInteger(n) && n > 0 ? n : undefined;
  }, [debouncedTgId]);

  const inputInvalid =
    debouncedTgId.trim().length > 0 && tgIdParsed === undefined;

  const queryKey = useMemo(
    () => ["users", { tg_id: tgIdParsed, page }] as const,
    [tgIdParsed, page],
  );

  const { data, isLoading, isError, error } = useQuery({
    queryKey,
    queryFn: () =>
      api.users.list({
        tg_id: tgIdParsed,
        page,
        limit: PAGE_LIMIT,
      }),
    enabled: !inputInvalid,
  });

  const columns: Column<UserOut>[] = [
    {
      key: "tg_id",
      label: "TG ID",
      width: "140px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-base">{r.tg_id}</span>
      ),
    },
    {
      key: "username",
      label: "Username",
      render: (r) =>
        r.tg_username ? (
          <span className="text-text-base">@{r.tg_username}</span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "lang",
      label: "Lang",
      width: "70px",
      render: (r) => (
        <span className="font-mono text-[12px] text-text-muted">{r.lang}</span>
      ),
    },
    {
      key: "phone",
      label: "Phone",
      width: "150px",
      render: (r) =>
        r.phone_e164 ? (
          <span className="font-mono text-[12px] text-text-muted">
            {r.phone_e164}
          </span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "ref",
      label: "Ref",
      width: "100px",
      render: (r) =>
        r.referral_source ? (
          <span className="text-text-muted">{r.referral_source}</span>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "banned",
      label: "Banned",
      width: "90px",
      render: (r) =>
        r.banned ? (
          <StatusBadge status="REVOKED">banned</StatusBadge>
        ) : (
          <span className="text-text-muted/50">—</span>
        ),
    },
    {
      key: "created",
      label: "Created",
      width: "150px",
      render: (r) => new Date(r.created_at).toLocaleString("ru-RU"),
    },
    {
      key: "actions",
      label: "",
      width: "120px",
      align: "right",
      render: (r) => (
        <Link to={`/subscriptions?user_id=${r.tg_id}`}>
          <PillButton variant="ghost" size="sm">
            Subs →
          </PillButton>
        </Link>
      ),
    },
  ];

  const total = data?.total ?? 0;

  return (
    <div>
      <PageHeading title="Users" subtitle={`Всего: ${total}`} />

      <Card padded className="mb-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <FormField
            label="TG ID"
            error={inputInvalid ? "Должно быть положительное число" : undefined}
          >
            <Input
              placeholder="например, 123456789"
              inputMode="numeric"
              value={tgIdInput}
              onChange={(e) => {
                setTgIdInput(e.target.value);
                setPage(1);
              }}
            />
          </FormField>
          <div className="flex items-end">
            <PillButton
              variant="ghost"
              size="sm"
              onClick={() => {
                setTgIdInput("");
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
        rowKey={(r) => String(r.tg_id)}
        loading={isLoading}
        empty="Пользователей не найдено"
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
