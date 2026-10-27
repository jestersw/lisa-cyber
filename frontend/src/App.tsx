import { useEffect } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AgentCreate } from "./pages/AgentCreate";
import { AgentDetail } from "./pages/AgentDetail";
import { AgentList } from "./pages/AgentList";
import { ApplicationPlugins } from "./pages/ApplicationPlugins";
import { BehaviorTemplates } from "./pages/BehaviorTemplates";
import { Dashboard } from "./pages/Dashboard";
import { LandingPage } from "./pages/LandingPage";
import { Login } from "./pages/Login";
import { MlStatus } from "./pages/MlStatus";
import { Range } from "./pages/Range";
import { Roles } from "./pages/Roles";

export function App() {
  const navigate = useNavigate();

  // A 401 anywhere (e.g. an expired token) clears auth and routes back to login.
  useEffect(() => {
    const onExpired = () => navigate("/login", { replace: true });
    window.addEventListener("lisa:auth-expired", onExpired);
    return () => window.removeEventListener("lisa:auth-expired", onExpired);
  }, [navigate]);

  return (
    <Routes>
      {/* Landing page has its own top nav; render it outside the panel Layout. */}
      <Route path="/" element={<LandingPage />} />
      <Route path="/login" element={<Login />} />

      {/* Panel routes require an operator token and share the Layout. */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/range" element={<Range />} />
          <Route path="/agents" element={<AgentList />} />
          <Route path="/agents/create" element={<AgentCreate />} />
          <Route path="/agents/:agentId" element={<AgentDetail />} />
          <Route path="/roles" element={<Roles />} />
          <Route path="/behavior-templates" element={<BehaviorTemplates />} />
          <Route path="/application-plugins" element={<ApplicationPlugins />} />
          <Route path="/model" element={<MlStatus />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Route>
      </Route>
    </Routes>
  );
}
