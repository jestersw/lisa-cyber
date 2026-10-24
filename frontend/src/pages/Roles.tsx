import { useCallback, useEffect, useState } from "react";
import { ApiError, endpoints, type Role } from "../api/client";

export function Roles() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    endpoints
      .roles()
      .then(setRoles)
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

  async function create() {
    if (!name.trim()) {
      setError("Role name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await endpoints.createRole({
        name: name.trim(),
        category: category.trim() || undefined,
        description: description.trim() || undefined,
      });
      setName("");
      setCategory("");
      setDescription("");
      load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(role: Role) {
    try {
      await endpoints.updateRole(role.id, { is_active: !role.is_active });
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  async function remove(role: Role) {
    if (!window.confirm(`Delete role "${role.name}"?`)) {
      return;
    }
    try {
      await endpoints.deleteRole(role.id);
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  return (
    <main className="page">
      <div className="sec-head">Catalog</div>
      <h1>Roles</h1>
      <p className="page-sub">
        The job roles agents can take. A role groups behaviour templates and drives which model is
        used for next-activity prediction.
      </p>

      {error && <div className="notice error">{error}</div>}

      <div className="form">
        <div className="field-row">
          <div className="field">
            <label htmlFor="role-name">Name</label>
            <input
              id="role-name"
              value={name}
              placeholder="developer"
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="role-category">Category</label>
            <input
              id="role-category"
              value={category}
              placeholder="engineering"
              onChange={(e) => setCategory(e.target.value)}
            />
          </div>
        </div>
        <div className="field">
          <label htmlFor="role-desc">Description</label>
          <input
            id="role-desc"
            value={description}
            placeholder="Writes code, runs a terminal, reviews PRs"
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <button className="btn primary" onClick={create} disabled={busy}>
          {busy ? "Adding…" : "Add role"}
        </button>
      </div>

      {roles.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Category</th>
              <th>Description</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {roles.map((role) => (
              <tr key={role.id}>
                <td>{role.name}</td>
                <td>{role.category ?? "-"}</td>
                <td>{role.description ?? "-"}</td>
                <td>
                  <span className={`status ${role.is_active ? "ready" : "offline"}`}>
                    {role.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td className="row-actions">
                  <button className="btn small" onClick={() => toggleActive(role)}>
                    {role.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button className="btn small danger" onClick={() => remove(role)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">No roles yet. Add the first one above.</p>
      )}
    </main>
  );
}
