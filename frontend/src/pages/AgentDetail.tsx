import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  endpoints,
  BASE_URL,
  ApiError,
  type AgentStatus,
  type Deployment,
  type DeploymentPackage,
  type Diagnosis,
  type HeartbeatLog,
  type Host,
  type NextActivity,
  type RunStatus,
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
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [savedHosts, setSavedHosts] = useState<Host[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [force, setForce] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [diagnoseError, setDiagnoseError] = useState<string | null>(null);
  const [run, setRun] = useState<RunStatus | null>(null);
  const [runBusy, setRunBusy] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) {
      return;
    }
    let active = true;

    endpoints
      .agentConfig(agentId)
      .then((value) => {
        if (active) {
          setPkg(value);
        }
      })
      .catch(() => {
        if (active) {
          setPkg(null);
        }
      });

    endpoints
      .hosts()
      .then((value) => {
        if (active) {
          setSavedHosts(value);
        }
      })
      .catch(() => {
        if (active) {
          setSavedHosts([]);
        }
      });

    const load = () => {
      endpoints
        .agentStatus(agentId)
        .then((value) => {
          if (active) {
            setStatus(value);
            setError(null);
          }
        })
        .catch((err: Error) => {
          if (active) {
            setError(err.message);
          }
        });
      endpoints
        .agentHeartbeats(agentId)
        .then((value) => {
          if (active) {
            setHeartbeats(value);
          }
        })
        .catch(() => {
          if (active) {
            setHeartbeats(null);
          }
        });
      endpoints
        .nextActivity(agentId)
        .then((value) => {
          if (active) {
            setPrediction(value);
          }
        })
        .catch(() => {
          if (active) {
            setPrediction(null);
          }
        });
      endpoints
        .deployments(agentId)
        .then((value) => {
          if (active) {
            setDeployments(value);
          }
        })
        .catch(() => {
          if (active) {
            setDeployments([]);
          }
        });
      endpoints
        .runStatus(agentId)
        .then((value) => {
          if (active) {
            setRun(value);
          }
        })
        .catch(() => {
          if (active) {
            setRun(null);
          }
        });
    };

    load();
    const timer = setInterval(load, 5000);

    return () => {
      active = false;
      clearInterval(timer);
    };
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

  const submitDeploy = async () => {
    const chosen = savedHosts.filter((h) => selected.includes(h.id));
    if (chosen.length === 0) {
      setDeployError("Select at least one host.");
      return;
    }
    setDeploying(true);
    setDeployError(null);
    try {
      await endpoints.deployAgent(agentId, {
        targets: chosen.map((h) => ({ host: h.address, ssh_user: h.ssh_user })),
        force,
      });
      setSelected([]);
      const latest = await endpoints.deployments(agentId);
      setDeployments(latest);
    } catch (err) {
      setDeployError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDeploying(false);
    }
  };

  const toggleHost = (id: number) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));

  const toggleRun = async () => {
    setRunBusy(true);
    setRunError(null);
    try {
      setRun(run?.running ? await endpoints.stopRun(agentId) : await endpoints.startRun(agentId));
    } catch (err) {
      setRunError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setRunBusy(false);
    }
  };

  const runDiagnose = async () => {
    setDiagnosing(true);
    setDiagnoseError(null);
    try {
      setDiagnosis(await endpoints.diagnoseAgent(agentId));
    } catch (err) {
      setDiagnoseError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setDiagnosing(false);
    }
  };

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

      {agent && (agent.installer_url || agent.binary_url) && (
        <div className="actions">
          {agent.installer_url && (
            <a className="btn primary" href={`${BASE_URL}${agent.installer_url}`} download>
              Download installer
            </a>
          )}
          {agent.binary_url && (
            <a className="btn" href={`${BASE_URL}${agent.binary_url}`} download>
              Download raw binary
            </a>
          )}
        </div>
      )}

      <section className="run-panel">
        <div className="diagnose-head">
          <h2 className="section-title">Demo run</h2>
          <button
            className={`btn ${run?.running ? "danger" : "primary"}`}
            onClick={toggleRun}
            disabled={runBusy}
          >
            {runBusy ? "…" : run?.running ? "■ Stop" : "▶ Run agent"}
          </button>
        </div>
        <p className="field-hint">
          Launch this agent's activity from the panel — no terminal. The server simulates its
          behaviour (opens apps, acts, idles, glances) so the{" "}
          <Link to="/range">live range view</Link> lights up. For a real agent on a real host, use
          the installer or “Deploy to hosts” below.
        </p>
        {runError && <div className="notice error">{runError}</div>}
        <p className="page-sub">
          <span className={`status ${run?.running ? "online" : "offline"}`}>
            {run?.running ? "running" : "stopped"}
          </span>
          {run?.running && run.started_at ? `  ·  since ${formatTime(run.started_at)}` : ""}
        </p>
      </section>

      <section className="diagnose-panel">
        <div className="diagnose-head">
          <h2 className="section-title">Behaviour diagnosis</h2>
          <button className="btn" onClick={runDiagnose} disabled={diagnosing}>
            {diagnosing ? "Analysing…" : "Diagnose"}
          </button>
        </div>
        <p className="field-hint">
          Collects this agent's heartbeats, activity events and build status and asks the LLM
          why it may be misbehaving, with suggested config fixes.
        </p>
        {diagnoseError && <div className="notice error">{diagnoseError}</div>}
        {diagnosis && (
          <div className="diagnose-result">
            <p className="diagnose-summary">
              {diagnosis.summary}
              <span className="diagnose-source">
                {diagnosis.source === "model" ? "LLM" : "no LLM — signals only"}
              </span>
            </p>
            {diagnosis.findings.length > 0 && (
              <ul className="diagnose-findings">
                {diagnosis.findings.map((f, i) => (
                  <li key={i} className={`finding ${f.severity}`}>
                    <span className="finding-sev">{f.severity}</span>
                    {f.issue}
                    {f.evidence ? <span className="finding-ev"> — {f.evidence}</span> : null}
                  </li>
                ))}
              </ul>
            )}
            {diagnosis.suggested_changes.length > 0 && (
              <>
                <h3 className="diagnose-subtitle">Suggested changes</h3>
                <ul className="diagnose-changes">
                  {diagnosis.suggested_changes.map((c, i) => (
                    <li key={i}>
                      <strong>{c.target}</strong>: {c.change}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {diagnosis.findings.length === 0 && diagnosis.suggested_changes.length === 0 && (
              <p className="empty">No issues detected.</p>
            )}
          </div>
        )}
      </section>

      {agent?.installer_url && (
        <section className="deploy-panel">
          <h2 className="section-title">Deploy to hosts</h2>
          <p className="field-hint">
            Push this agent onto saved range hosts over SSH via Ansible — each gets it installed
            and kept running. Manage your targets on the <Link to="/hosts">Hosts</Link> page.
          </p>
          {savedHosts.length === 0 ? (
            <p className="empty">
              No saved hosts. Add your range's machines on the <Link to="/hosts">Hosts</Link> page,
              then pick them here.
            </p>
          ) : (
            <div className="host-pick">
              {savedHosts.map((h) => (
                <label key={h.id} className={`host-opt${selected.includes(h.id) ? " on" : ""}`}>
                  <input
                    type="checkbox"
                    checked={selected.includes(h.id)}
                    onChange={() => toggleHost(h.id)}
                  />
                  <span className="host-opt-label">{h.label}</span>
                  <span className="host-opt-addr mono">{h.address}</span>
                  {h.os_type && <span className="host-opt-os">{h.os_type}</span>}
                </label>
              ))}
            </div>
          )}
          <div className="deploy-controls">
            <label className="deploy-check">
              <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
              Force reinstall / update
            </label>
            <button
              className="btn primary"
              onClick={submitDeploy}
              disabled={deploying || selected.length === 0}
            >
              {deploying ? "Deploying…" : `Deploy to ${selected.length || "…"} host(s)`}
            </button>
          </div>
          {deployError && <div className="notice error">{deployError}</div>}

          {deployments.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Status</th>
                  <th>Result</th>
                </tr>
              </thead>
              <tbody>
                {deployments.map((d) => (
                  <tr key={d.id}>
                    <td>{formatTime(d.created_at)}</td>
                    <td>
                      <span className={`status ${d.status}`}>{d.status}</span>
                    </td>
                    <td className="deploy-result">
                      {d.status === "unavailable"
                        ? (d.error ?? "ansible unavailable")
                        : d.status === "failed"
                          ? (d.error ?? `exit ${d.returncode ?? "?"}`)
                          : d.status === "succeeded"
                            ? "ok"
                            : "…"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}

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
          {prediction && (
            <div className="field-hint">
              {prediction.source === "model"
                ? `from ${prediction.trained_on ?? "model"}`
                : "no model yet, falling back"}
            </div>
          )}
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

      {prediction?.distribution && (
        <>
          <h2 className="section-title">Next application</h2>
          <div className="dist-list">
            {Object.entries(prediction.distribution)
              .sort((a, b) => b[1] - a[1])
              .map(([app, share]) => (
                <div className="dist-row" key={app}>
                  <span className="dist-app">{app}</span>
                  <span className="dist-bar">
                    <span className="dist-fill" style={{ width: `${Math.round(share * 100)}%` }} />
                  </span>
                  <span className="dist-share">{Math.round(share * 100)}%</span>
                </div>
              ))}
          </div>
          <p className="field-hint">
            Learned from activity logs; the agent samples from this distribution.
          </p>
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
