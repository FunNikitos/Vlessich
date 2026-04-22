import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AuditPage } from "@/pages/Audit";
import { CodesPage } from "@/pages/Codes";
import { DashboardPage } from "@/pages/Dashboard";
import { LoginPage } from "@/pages/Login";
import { NodesPage } from "@/pages/Nodes";
import { SubscriptionsPage } from "@/pages/Subscriptions";
import { UsersPage } from "@/pages/Users";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="codes" element={<CodesPage />} />
        <Route path="users" element={<UsersPage />} />
        <Route path="subscriptions" element={<SubscriptionsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="nodes" element={<NodesPage />} />
      </Route>
    </Routes>
  );
}
