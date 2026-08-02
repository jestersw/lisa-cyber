import { endpoints, type Agent } from "../api/client";
import { usePolling } from "../hooks/usePolling";

const REFRESH_MS = 30_000;

export function Dashboard() {
  const { data, error } = usePolling<Agent[]>(endpoints.agents, REFRESH_MS);
  const agents = data ?? [];

  const online = agents.filter((a) => a.status === "online" || a.status === "active").length;
  const offline = agents.length - online;

  return (
    <main className="page">
      <div className="sec-head">Overview</div>
      <h1>Simulation status</h1>
      <p className="page-sub">
        Live picture of the simulated workforce running inside the range.
      </p>

      {error && <div className="notice error">Backend unreachable: {error}</div>}

      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">Total agents</div>
          <div className="stat-value">{agents.length}</div>
        </div>
        <div className="card">
          <div className="stat-label">Active</div>
          <div className="stat-value">{online}</div>
        </div>
        <div className="card">
          <div className="stat-label">Idle / offline</div>
          <div className="stat-value">{offline}</div>
        </div>
      </div>
    </main>
  );
}
