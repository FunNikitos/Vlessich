import { NavLink, Route, Routes } from "react-router-dom";
import { DashboardPage } from "@/pages/Dashboard";
import { CodesPage } from "@/pages/Codes";
import { UsersPage } from "@/pages/Users";
import { NodesPage } from "@/pages/Nodes";

export function App() {
  return (
    <div className="mx-auto flex min-h-full max-w-6xl gap-6 p-6">
      <aside className="w-56 shrink-0 space-y-1">
        <h1 className="font-title text-[20px] font-bold mb-4">Vlessich · Admin</h1>
        <NavItem to="/">Dashboard</NavItem>
        <NavItem to="/codes">Codes</NavItem>
        <NavItem to="/users">Users</NavItem>
        <NavItem to="/nodes">Nodes</NavItem>
      </aside>
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/codes" element={<CodesPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/nodes" element={<NodesPage />} />
        </Routes>
      </main>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        [
          "block rounded-md px-3 py-2 text-sm",
          isActive
            ? "bg-bg-elevated text-text-base"
            : "text-text-muted hover:text-text-base hover:bg-bg-elevated/60",
        ].join(" ")
      }
    >
      {children}
    </NavLink>
  );
}
