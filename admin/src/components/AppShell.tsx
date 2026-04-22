/** App shell with sidebar nav, role badge, sign-out. */
import { NavLink, Outlet } from "react-router-dom";
import type { ReactNode } from "react";
import { PillButton, RoleBadge } from "@/components";
import { useAuth } from "@/hooks/useAuth";

export function AppShell() {
  const { auth, logout } = useAuth();
  if (!auth) return null;

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col gap-6 border-r border-border-base/30 bg-bg-elevated p-5">
        <h1 className="font-title text-[18px] font-bold uppercase tracking-[2px]">
          Vlessich<span className="text-brand-green"> · </span>Admin
        </h1>

        <nav className="flex flex-col gap-1">
          <NavItem to="/">Dashboard</NavItem>
          <NavItem to="/codes">Codes</NavItem>
          <NavItem to="/users">Users</NavItem>
          <NavItem to="/subscriptions">Subscriptions</NavItem>
          <NavItem to="/audit">Audit</NavItem>
          <NavItem to="/nodes">Nodes</NavItem>
        </nav>

        <div className="mt-auto flex flex-col gap-3 border-t border-border-base/30 pt-4">
          <div className="flex flex-col gap-1.5">
            <span className="truncate text-sm text-text-base">{auth.email}</span>
            <RoleBadge role={auth.role} />
          </div>
          <PillButton
            variant="ghost"
            size="sm"
            onClick={logout}
            className="w-full"
          >
            Sign out
          </PillButton>
        </div>
      </aside>

      <main className="flex-1 bg-bg-base p-8">
        <Outlet />
      </main>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        [
          "rounded-md px-3 py-2 text-[11.5px] font-bold uppercase tracking-[1.6px] transition",
          isActive
            ? "bg-brand-green/15 text-brand-green"
            : "text-text-muted hover:bg-bg-mid hover:text-text-base",
        ].join(" ")
      }
    >
      {children}
    </NavLink>
  );
}
