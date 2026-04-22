import { useState } from "react";
import { Link } from "react-router-dom";
import { mutate } from "swr";
import { useSubscription, SUBSCRIPTION_KEY } from "@/hooks/useSubscription";
import {
  Card,
  CopyButton,
  PillButton,
  QRCodeBlock,
  SkeletonBlock,
} from "@/components";
import { api } from "@/lib/api";
import { buildDeeplinks } from "@/lib/deeplinks";

export function SubscriptionPage() {
  const { data, error, isLoading, mutate: refetch } = useSubscription();
  const [resetting, setResetting] = useState<string | null>(null);
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const [resetError, setResetError] = useState<string | null>(null);

  if (isLoading && !data) {
    return (
      <>
        <BackHeader />
        <SkeletonBlock height="240px" radius="8px" />
        <SkeletonBlock height="48px" radius="9999px" />
        <SkeletonBlock height="48px" radius="9999px" />
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

  const links = buildDeeplinks(data.urls);

  async function handleReset(deviceId: string) {
    setResetting(deviceId);
    setResetError(null);
    try {
      await api.resetDevice(deviceId);
      await mutate(SUBSCRIPTION_KEY);
      setConfirmId(null);
    } catch (e) {
      setResetError((e as Error).message);
    } finally {
      setResetting(null);
    }
  }

  return (
    <>
      <BackHeader />

      <Card elevated>
        <p className="mb-3 text-center text-xs uppercase tracking-[1.4px] text-text-muted">
          Сканируйте QR в VPN-клиенте
        </p>
        <QRCodeBlock value={data.urls.raw} />
        <div className="mt-4 flex justify-center">
          <CopyButton value={data.urls.raw} label="Копировать ссылку" />
        </div>
      </Card>

      <h2 className="mt-2 px-1 text-xs uppercase tracking-[2px] text-text-muted">
        Импорт в клиент
      </h2>
      {links.map((link) => (
        <Card key={link.url}>
          <PillButton
            variant="secondary"
            onClick={() => (window.location.href = link.url)}
          >
            {link.label}
          </PillButton>
        </Card>
      ))}

      {data.devices.length > 0 && (
        <>
          <h2 className="mt-2 px-1 text-xs uppercase tracking-[2px] text-text-muted">
            Устройства ({data.devices.length}/{data.devices_limit})
          </h2>
          {data.devices.map((d) => (
            <Card key={d.id}>
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-bold">{d.name ?? "Устройство"}</p>
                  {d.ip_hash_short && (
                    <p className="text-xs text-text-muted">
                      IP: {d.ip_hash_short}
                    </p>
                  )}
                </div>
                {confirmId === d.id ? (
                  <div className="flex gap-2">
                    <PillButton
                      variant="ghost"
                      size="sm"
                      onClick={() => setConfirmId(null)}
                    >
                      Отмена
                    </PillButton>
                    <PillButton
                      size="sm"
                      loading={resetting === d.id}
                      onClick={() => handleReset(d.id)}
                    >
                      Сбросить
                    </PillButton>
                  </div>
                ) : (
                  <PillButton
                    variant="ghost"
                    size="sm"
                    onClick={() => setConfirmId(d.id)}
                  >
                    Сбросить
                  </PillButton>
                )}
              </div>
            </Card>
          ))}
          {resetError && (
            <Card>
              <p className="text-sm text-negative">{resetError}</p>
            </Card>
          )}
        </>
      )}
    </>
  );
}

function BackHeader() {
  return (
    <header className="flex items-center justify-between pt-2">
      <h1 className="font-title text-[20px] font-bold tracking-wide">
        ПОДПИСКА
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
