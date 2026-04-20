export function CodesPage() {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-title text-[24px] font-bold">Codes</h2>
        <button className="btn-pill">+ New code</button>
      </div>
      <div className="card">
        <p className="text-text-muted text-sm">
          TODO: генерация кодов партиями, фильтр по статусу/тегу, экспорт CSV,
          отзыв кодов (TZ §5).
        </p>
      </div>
    </section>
  );
}
