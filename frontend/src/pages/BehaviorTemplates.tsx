import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  endpoints,
  type BehaviorTemplate,
  type Role,
} from "../api/client";

const OS_OPTIONS = ["linux", "macos", "windows"];

export function BehaviorTemplates() {
  const [templates, setTemplates] = useState<BehaviorTemplate[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [osType, setOsType] = useState("linux");
  const [description, setDescription] = useState("");
  const [roleId, setRoleId] = useState<number | "">("");
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [draftName, setDraftName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    endpoints
      .behaviorTemplates()
      .then(setTemplates)
      .catch((err: Error) => setError(err.message));
    endpoints
      .roles()
      .then(setRoles)
      .catch(() => setRoles([]));
  }, []);

  useEffect(load, [load]);

  const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : String(err));
  const roleName = (id: number | null) => roles.find((r) => r.id === id)?.name ?? "-";

  async function generate() {
    if (!description.trim()) {
      setError("A role description is required to generate a template.");
      return;
    }
    setBusy(true);
    setError(null);
    setDraft(null);
    try {
      const res = await endpoints.generateTemplate({
        description: description.trim(),
        os_type: osType,
        name: name.trim() || undefined,
      });
      setDraft(res.template_data);
      setDraftName(name.trim() || res.name);
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
    if (roleId === "") {
      setError("Pick a role before saving the template.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await endpoints.createBehaviorTemplate({
        name: draftName,
        role_id: roleId,
        template_data: draft,
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

  async function toggleActive(t: BehaviorTemplate) {
    try {
      await endpoints.updateBehaviorTemplate(t.id, { is_active: !t.is_active });
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function remove(t: BehaviorTemplate) {
    if (!window.confirm(`Delete template "${t.name}"?`)) {
      return;
    }
    try {
      await endpoints.deleteBehaviorTemplate(t.id);
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  return (
    <main className="page">
      <div className="sec-head">Catalog</div>
      <h1>Behavior templates</h1>
      <p className="page-sub">
        Which applications a role runs and when. Describe a role, generate a draft with the LLM,
        attach it to a role and save it.
      </p>

      {error && <div className="notice error">{error}</div>}

      <div className="form">
        <div className="field-row">
          <div className="field">
            <label htmlFor="tpl-name">Name (optional)</label>
            <input
              id="tpl-name"
              value={name}
              placeholder="Backend developer, weekdays"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="tpl-os">OS</label>
            <select id="tpl-os" value={osType} onChange={(e) => setOsType(e.target.value)}>
              {OS_OPTIONS.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label htmlFor="tpl-desc">Role description</label>
          <input
            id="tpl-desc"
            value={description}
            placeholder="A backend developer who lives in the terminal and an IDE"
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
            <h2 className="section-title">Draft: {draftName}</h2>
            <div className="row-actions">
              <select value={roleId} onChange={(e) => setRoleId(Number(e.target.value) || "")}>
                <option value="">— pick role —</option>
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
              <button className="btn primary" onClick={save} disabled={busy}>
                Save
              </button>
              <button className="btn" onClick={() => setDraft(null)} disabled={busy}>
                Discard
              </button>
            </div>
          </div>
          <pre className="json-preview">{JSON.stringify(draft, null, 2)}</pre>
        </div>
      )}

      {templates.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>OS</th>
              <th>Version</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {templates.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{roleName(t.role_id)}</td>
                <td>{t.os_type}</td>
                <td>{t.version ?? "-"}</td>
                <td>
                  <span className={`status ${t.is_active ? "ready" : "offline"}`}>
                    {t.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="row-actions">
                  <button className="btn small" onClick={() => toggleActive(t)}>
                    {t.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button className="btn small danger" onClick={() => remove(t)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">No templates yet. Generate one above.</p>
      )}
    </main>
  );
}
