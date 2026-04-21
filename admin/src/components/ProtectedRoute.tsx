/** Protected route: requires valid JWT; optional role gate. */
import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { hasRole } from "@/lib/auth";
import type { Role } from "@/lib/types";

export interface ProtectedRouteProps {
  children: ReactNode;
  requiredRole?: Role;
}

export function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const { auth } = useAuth();
  if (!auth) return <Navigate to="/login" replace />;
  if (requiredRole && !hasRole(auth.role, requiredRole)) {
    return <ForbiddenScreen />;
  }
  return <>{children}</>;
}

function ForbiddenScreen() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="max-w-sm text-center">
        <h1 className="font-title text-[24px] font-bold uppercase tracking-[2px]">
          403
        </h1>
        <p className="mt-2 text-sm text-text-muted">
          Недостаточно прав для просмотра этой страницы.
        </p>
      </div>
    </div>
  );
}
