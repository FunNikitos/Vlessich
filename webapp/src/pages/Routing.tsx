import { useState } from "react";
import { Link } from "react-router-dom";
import { useSubscription, SUBSCRIPTION_KEY } from "@/hooks/useSubscription";
import { mutate } from "swr";
import { Card, PillButton, SkeletonBlock, Toggle } from "@/components";
import { api, type SubscriptionResponse } from "@/lib/api";

export function RoutingPage() {
  const { data, error, isLoading, mutate: refetch } = useSubscription();
  const [busy, setBusy] = useState<"adblock" | "smart_routing" | null>(null);
  const [toggleError, setToggleError] = useState<string | null>(null);

  async function handleToggle(
    field: "adblock" | "smart_routing",
    next: boolean,
  ) {
    if (!data) return;
    const baseline: SubscriptionResponse = data;
    setBusy(field);
    setToggleError(null);
    const optimistic: SubscriptionResponse = { ...baseline, [field]: next };
    try {
      await mutate(SUBSCRIPTION_KEY, api.toggleRouting({ [field]: next }), {
        optimisticData: optimistic,
        rollbackOnError: true,
        populateCache: (result, current) => ({
          ...(current ?? baseline),
          ...result,
        }),
        revalidate: false,
      });
    } catch (e) {
      setToggleError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  if (isLoading && !data) {
    return (
      <>
        <BackHeader />
        <SkeletonBlock height="88px" radius="8px" />
        <SkeletonBlock height="88px" radius="8px" />
      </>
    );
  }

  if (error) {
    return (
      <>
        <BackHeader />
        <Card>
          <p className="text-negative">Ошибка</p>
          <p className="mt-2 text-sm text-text-muted">
            {(error as Error).message}
          </p>
          <div className="mt-4">
            <PillButton variant="secondary" size="sm" onClick={() => refetch()}>
              Повторить
            </PillButton>
          </div>
        </Card>
      </>
    );
  }

  if (!data) return null;

  return (
    <>
      <BackHeader />

      <Card elevated>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <p className="font-bold">Adblock</p>
            <p className="mt-1 text-sm text-text-muted">
              Блокировка рекламы и трекеров через AGH DNS.
            </p>
          </div>
          <Toggle
            checked={data.adblock}
            disabled={busy === "adblock"}
            onChange={(v) => handleToggle("adblock", v)}
            label="Adblock"
          />
        </div>
      </Card>

      <Card elevated>
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <p className="font-bold">Smart routing</p>
            <p className="mt-1 text-sm text-text-muted">
              Российские сайты — напрямую, остальное — через VPN.
            </p>
          </div>
          <Toggle
            checked={data.smart_routing}
            disabled={busy === "smart_routing"}
            onChange={(v) => handleToggle("smart_routing", v)}
            label="Smart routing"
          />
        </div>
      </Card>

      {toggleError && (
        <Card>
          <p className="text-sm text-negative">{toggleError}</p>
        </Card>
      )}
    </>
  );
}

function BackHeader() {
  return (
    <header className="flex items-center justify-between pt-2">
      <h1 className="font-title text-[20px] font-bold tracking-wide">
        МАРШРУТИЗАЦИЯ
      </h1>
      <Link
        to="/"
        className="text-xs uppercase tracking-[1.4px] text-text-muted hover:text-text-base"
      >
        Назад
      </Link>
    </header>
  );
}
