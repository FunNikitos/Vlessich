import { Link } from "react-router-dom";

export function HomePage() {
  return (
    <>
      <header className="pt-2">
        <h1 className="font-title text-[24px] font-bold">Vlessich</h1>
        <p className="mt-1 text-sm text-text-muted">Приватный VPN для РФ</p>
      </header>

      <section className="card flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <span className="text-text-muted text-sm uppercase tracking-[1.4px]">План</span>
          <span className="font-semibold">TODO</span>
        </div>
        <div className="flex items-baseline justify-between">
          <span className="text-text-muted text-sm uppercase tracking-[1.4px]">Действует до</span>
          <span className="font-semibold">—</span>
        </div>
      </section>

      <Link to="/subscription" className="btn-pill">Показать подписку</Link>
      <Link to="/routing" className="btn-ghost">Smart-routing</Link>
    </>
  );
}
