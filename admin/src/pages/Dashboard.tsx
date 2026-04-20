export function DashboardPage() {
  return (
    <section className="space-y-4">
      <h2 className="font-title text-[24px] font-bold">Dashboard</h2>
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="Users" value="—" />
        <StatCard label="Active subs" value="—" />
        <StatCard label="Nodes healthy" value="—" />
      </div>
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="card">
      <div className="text-text-muted text-xs uppercase tracking-[1.4px]">{label}</div>
      <div className="mt-2 font-title text-[28px] font-bold">{value}</div>
    </div>
  );
}
