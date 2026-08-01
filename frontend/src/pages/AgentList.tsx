import { Link } from "react-router-dom";
import { endpoints, type Agent } from "../api/client";
import { usePolling } from "../hooks/usePolling";

const REFRESH_MS = 30_000;

function formatSeen(value: string | null): string {
  if (!value) {
    return "never";
  }
  return new Date(value).toLocaleString();
}

export function AgentList() {
  const { data, error, loading } = usePolling<Agent[]>(endpoints.agents, REFRESH_MS);
  const agents = data ?? [];

  return (
    <main className="page">
      <div className="sec-head">Agents</div>
      <h1>Simulated workforce</h1>
      <p className="page-sub">Every configured agent, its target OS and last heartbeat.</p>

      {error && <div className="notice error">Backend unreachable: {error}</div>}

      {!error && !loading && agents.length === 0 && (
        <p className="empty">
          No agents yet. <Link to="/agents/create">Create the first one.</Link>
        </p>
      )}

      {agents.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>ID</th>
              <th>OS</th>
              <th>Status</th>
              <th>Last seen</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent) => (
              <tr key={agent.agent_id}>
                <td>
                  <Link to={`/agents/${agent.agent_id}`}>{agent.name}</Link>
                </td>
                <td>{agent.agent_id}</td>
                <td>{agent.os_type}</td>
                <td>
                  <span className={`status ${agent.status}`}>{agent.status}</span>
                </td>
                <td>{formatSeen(agent.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
