import { useCallback, useEffect, useState } from "react";
import { ApiError, endpoints, type MlStatus as MlStatusData } from "../api/client";

export function MlStatus() {
  const [status, setStatus] = useState<MlStatusData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(() => {
    endpoints
      .mlStatus()
      .then((s) => {
        setStatus(s);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  async function reload() {
    setBusy(true);
    setNote(null);
    setError(null);
    try {
      const res = await endpoints.mlReload();
      setNote(res.reloaded ? "Models reloaded from disk." : "Reloaded — no shared model on disk.");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <div className="sec-head">Model</div>
      <h1>Next-activity model</h1>
      <p className="page-sub">
        The transition model that drives agents' next-app choices. Trained from activity logs and
        served as the <code>counts</code> artifact; reload after retraining to pick up new models.
      </p>

      {error && <div className="notice error">{error}</div>}
      {note && <div className="notice success">{note}</div>}

      <div className="stat-grid">
        <div className="card">
          <div className="stat-label">Shared model</div>
          <div className="stat-value small">
            {status ? (status.shared_loaded ? "loaded" : "not trained yet") : "-"}
          </div>
          {status && !status.shared_loaded && (
            <div className="field-hint">
              No model on disk — agents fall back until logs are collected and a model is trained.
            </div>
          )}
        </div>
        <div className="card">
          <div className="stat-label">States learned</div>
          <div className="stat-value small">{status ? status.shared_states : "-"}</div>
        </div>
        <div className="card">
          <div className="stat-label">Models directory</div>
          <div className="stat-value small mono">{status ? status.models_dir : "-"}</div>
        </div>
      </div>

      <div className="actions">
        <button className="btn primary" onClick={reload} disabled={busy}>
          {busy ? "Reloading…" : "Reload models"}
        </button>
      </div>
    </main>
  );
}
