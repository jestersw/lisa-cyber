import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AgentCreate } from "./pages/AgentCreate";
import { AgentDetail } from "./pages/AgentDetail";
import { AgentList } from "./pages/AgentList";
import { Dashboard } from "./pages/Dashboard";
import { LandingPage } from "./pages/LandingPage";

export function App() {
  return (
    <Routes>
      {/* Landing page has its own top nav; render it outside the panel Layout. */}
      <Route path="/" element={<LandingPage />} />

      {/* Panel routes share the Layout (header, container). */}
      <Route element={<Layout />}>
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/agents" element={<AgentList />} />
        <Route path="/agents/create" element={<AgentCreate />} />
        <Route path="/agents/:agentId" element={<AgentDetail />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}
