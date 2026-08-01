import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  endpoints,
  type AgentStatus,
  type DeploymentPackage,
  type HeartbeatLog,
  type NextActivity,
} from "../api/client";

const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatTime(value: string | null): string {
  if (!value) {
    return "never";
  }
  return new Date(value).toLocaleString();
}

export function AgentDetail() {
  const { agentId = "" } = useParams();
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const [heartbeats, setHeartbeats] = useState<HeartbeatLog | null>(null);
  const [pkg, setPkg] = useState<DeploymentPackage | null>(null);
  const [prediction, setPrediction] = useState<NextActivity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) {
      return;
    }
    endpoints
      .agentStatus(agentId)
      .then(setStatus)
      .catch((err: Error) => setError(err.message));
    endpoints.agentHeartbeats(agentId).then(setHeartbeats).catch(() => setHeartbeats(null));
    endpoints.agentConfig(agentId).then(setPkg).catch(() => setPkg(null));
    endpoints.nextActivity(agentId).then(setPrediction).catch(() => setPrediction(null));
  }, [agentId]);

  if (error) {
    return (
      <main className="page">
        <div className="sec-head">Agent</div>
        <h1>{agentId}</h1>
        <div className="notice error">{error}</div>
        <p className="empty">
          <Link to="/agents">Back to agents</Link>
        </p>
      </main>
    );
  }

  const agent = status?.agent;
  const config = pkg?.agent_config;

  return (
    <main className="page">
      <div className="sec-head">Agent</div>
      <h1>{agent?.name ?? agentId}</h1>
      <p className="page-sub">
        <span className={`status ${agent?.status ?? ""}`}>{agent?.status ?? "unknown"}</span>
        {"  ·  "}
        {agent?.role ?? "no role"} · {agent?.os_type ?? "-"} · last seen{" "}
        {formatTime(agent?.last_seen ?? null)}
      </p>

      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">Agent id</div>
          <div className="stat-value small">{agentId}</div>
        </div>
        <div className="card">
          <div className="stat-label">Heartbeat</div>
          <div className="stat-value small">
            {config ? `${config.heartbeat.interval_minutes} min` : "-"}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Predicted next</div>
          <div className="stat-value small">{prediction?.next_activity ?? "-"}</div>
          {prediction && <div className="field-hint">source: {prediction.source}</div>}
        </div>
      </div>

      {config && (
        <>
          <h2 className="section-title">Schedule</h2>
          <div className="detail-grid">
            <div className="detail-item">
              <span className="detail-key">Workdays</span>
              <span className="detail-value">
                {config.schedule.workdays.map((d) => WEEKDAY_LABELS[d - 1]).join(" ")}
              </span>
            </div>
            <div className="detail-item">
              <span className="detail-key">Work hours</span>
              <span className="detail-value">
                {config.schedule.work_start} - {config.schedule.work_end}
              </span>
            </div>
            <div className="detail-item">
              <span className="detail-key">Lunch window</span>
              <span className="detail-value">
                {config.schedule.lunch.earliest} - {config.schedule.lunch.latest} (
                {config.schedule.lunch.min_minutes}-{config.schedule.lunch.max_minutes} min)
              </span>
            </div>
          </div>

          <h2 className="section-title">Behavior</h2>
          <div className="detail-grid">
            {Object.entries(config.behavior).map(([key, range]) => (
              <div className="detail-item" key={key}>
                <span className="detail-key">{key.replace(/_/g, " ")}</span>
                <span className="detail-value">
                  {range.min} - {range.max}
                </span>
              </div>
            ))}
          </div>

          <h2 className="section-title">Applications</h2>
          <div className="app-list">
            {config.applications.map((app) => (
              <span
                key={app}
                className={`app-chip ${pkg?.application_plugins[app] ? "selected" : ""}`}
              >
                {app}
                {pkg?.application_plugins[app] ? "" : " (no plugin)"}
              </span>
            ))}
          </div>
        </>
      )}

      <h2 className="section-title">Recent heartbeats</h2>
      {heartbeats && heartbeats.heartbeats.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Status</th>
              <th>Application</th>
              <th>Version</th>
            </tr>
          </thead>
          <tbody>
            {heartbeats.heartbeats.map((hb, index) => (
              <tr key={index}>
                <td>{formatTime(hb.timestamp)}</td>
                <td>{String(hb.data?.status ?? "-")}</td>
                <td>{String(hb.data?.application ?? "-")}</td>
                <td>{String(hb.data?.version ?? "-")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">No heartbeats received yet.</p>
      )}

      <p className="empty">
        <Link to="/agents">Back to agents</Link>
      </p>
    </main>
  );
}
