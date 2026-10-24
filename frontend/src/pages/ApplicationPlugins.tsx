import { useCallback, useEffect, useState } from "react";
import { ApiError, endpoints, type ApplicationTemplate } from "../api/client";

const OS_OPTIONS = ["linux", "macos", "windows"];

export function ApplicationPlugins() {
  const [plugins, setPlugins] = useState<ApplicationTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [osType, setOsType] = useState("linux");
  const [description, setDescription] = useState("");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    endpoints
      .applicationTemplates()
      .then(setPlugins)
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

  async function generate() {
    if (!name.trim()) {
      setError("Application name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setDraft(null);
    try {
      const res = await endpoints.generatePlugin({
        name: name.trim(),
        os_type: osType,
        description: description.trim() || undefined,
      });
      setDraft(res.template_config);
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!draft) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const info = (draft.app_info ?? {}) as Record<string, string>;
      await endpoints.createApplicationTemplate({
        name: name.trim(),
        display_name: info.display_name,
        category: info.category,
        template_config: draft,
        os_type: osType,
      });
      setDraft(null);
      setName("");
      setDescription("");
      load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(plugin: ApplicationTemplate) {
    try {
      await endpoints.updateApplicationTemplate(plugin.id, { is_active: !plugin.is_active });
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function remove(plugin: ApplicationTemplate) {
    if (!window.confirm(`Delete plugin "${plugin.name}"?`)) {
      return;
    }
    try {
      await endpoints.deleteApplicationTemplate(plugin.id);
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  return (
    <main className="page">
      <div className="sec-head">Catalog</div>
      <h1>Application plugins</h1>
      <p className="page-sub">
        How a simulated user installs, opens and uses one application. Generate a draft with the
        LLM, review it, then save it to the library so agents can be built with it.
      </p>

      {error && <div className="notice error">{error}</div>}

      <div className="form">
        <div className="field-row">
          <div className="field">
            <label htmlFor="plugin-name">Application</label>
            <input
              id="plugin-name"
              value={name}
              placeholder="slack"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="plugin-os">OS</label>
            <select id="plugin-os" value={osType} onChange={(e) => setOsType(e.target.value)}>
              {OS_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="plugin-desc">Hint (optional)</label>
          <input
            id="plugin-desc"
            value={description}
            placeholder="team chat, used all day"
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <button className="btn primary" onClick={generate} disabled={busy}>
          {busy ? "Working…" : "Generate with LLM"}
        </button>
      </div>

      {draft && (
        <div className="draft">
          <div className="draft-head">
            <h2 className="section-title">Draft: {name}</h2>
            <div className="row-actions">
              <button className="btn primary" onClick={save} disabled={busy}>
                Save to library
              </button>
              <button className="btn" onClick={() => setDraft(null)} disabled={busy}>
                Discard
              </button>
            </div>
          </div>
          <pre className="json-preview">{JSON.stringify(draft, null, 2)}</pre>
        </div>
      )}

      {plugins.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Display</th>
              <th>Category</th>
              <th>OS</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {plugins.map((p) => (
              <tr key={p.id}>
                <td>{p.name}</td>
                <td>{p.display_name ?? "-"}</td>
                <td>{p.category ?? "-"}</td>
                <td>{p.os_type}</td>
                <td>
                  <span className={`status ${p.is_active ? "ready" : "offline"}`}>
                    {p.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="row-actions">
                  <button className="btn small" onClick={() => toggleActive(p)}>
                    {p.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button className="btn small danger" onClick={() => remove(p)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">No plugins yet. Generate one above.</p>
      )}
    </main>
  );
}
