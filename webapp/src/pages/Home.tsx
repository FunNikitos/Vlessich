import { useNavigate } from "react-router-dom";
import { useBootstrap } from "@/hooks/useBootstrap";
import {
  Card,
  PillButton,
  SkeletonBlock,
  StatusBadge,
  statusFromBackend,
} from "@/components";

const BOT_USERNAME = import.meta.env.VITE_BOT_USERNAME ?? "vlessich_bot";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function daysUntil(iso: string | null): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Math.max(0, Math.ceil(ms / 86400000));
}

export function HomePage() {
  const navigate = useNavigate();
  const { data, error, isLoading, mutate } = useBootstrap();

  if (isLoading && !data) {
    return (
      <>
        <header className="pt-2">
          <h1 className="font-title text-[24px] font-bold">VLESSICH</h1>
          <SkeletonBlock width="40%" height="14px" className="mt-2" />
        </header>
        <SkeletonBlock height="120px" radius="8px" />
        <SkeletonBlock height="48px" radius="9999px" />
        <SkeletonBlock height="48px" radius="9999px" />
      </>
    );
  }

  if (error) {
    return (
      <>
        <header className="pt-2">
          <h1 className="font-title text-[24px] font-bold">VLESSICH</h1>
        </header>
        <Card>
          <p className="text-negative">Ошибка загрузки</p>
          <p className="mt-2 text-sm text-text-muted">
            {(error as Error).message}
          </p>
          <div className="mt-4">
            <PillButton variant="secondary" size="sm" onClick={() => mutate()}>
              Повторить
            </PillButton>
          </div>
        </Card>
      </>
    );
  }

  const sub = data?.subscription ?? null;
  const status = statusFromBackend(sub?.status);
  const days = daysUntil(sub?.expires_at ?? null);

  return (
    <>
      <header className="flex items-center justify-between pt-2">
        <h1 className="font-title text-[24px] font-bold tracking-wide">
          VLESSICH
        </h1>
        <StatusBadge status={status} />
      </header>

      {sub ? (
        <Card elevated>
          <div className="flex items-baseline justify-between">
            <span className="text-xs uppercase tracking-[1.4px] text-text-muted">
              План
            </span>
            <span className="font-bold">{sub.plan}</span>
          </div>
          <div className="mt-3 flex items-baseline justify-between">
            <span className="text-xs uppercase tracking-[1.4px] text-text-muted">
              Действует до
            </span>
            <span className="font-bold">{formatDate(sub.expires_at)}</span>
          </div>
          {days !== null && (
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-xs uppercase tracking-[1.4px] text-text-muted">
                Осталось
              </span>
              <span className="font-bold">{days} дн.</span>
            </div>
          )}
        </Card>
      ) : (
        <Card elevated>
          <p className="text-sm text-text-muted">
            У вас нет активной подписки.
          </p>
          <div className="mt-4">
            <PillButton
              onClick={() =>
                window.open(
                  `https://t.me/${BOT_USERNAME}?start=buy`,
                  "_blank",
                  "noopener",
                )
              }
            >
              Открыть бота
            </PillButton>
          </div>
        </Card>
      )}

      <PillButton
        disabled={!sub}
        onClick={() => navigate("/subscription")}
      >
        Показать подписку
      </PillButton>
      <PillButton
        variant="secondary"
        disabled={!sub}
        onClick={() => navigate("/routing")}
      >
        Настроить маршрутизацию
      </PillButton>
      <PillButton
        variant="ghost"
        onClick={() =>
          window.open(
            `https://t.me/${BOT_USERNAME}?start=mtproto`,
            "_blank",
            "noopener",
          )
        }
      >
        Получить MTProto
      </PillButton>
    </>
  );
}
