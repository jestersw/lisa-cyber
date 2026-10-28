import { useCallback, useEffect, useState } from "react";
import { ApiError, endpoints, type Host } from "../api/client";

export function Hosts() {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [address, setAddress] = useState("");
  const [sshUser, setSshUser] = useState("");
  const [osType, setOsType] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    endpoints
      .hosts()
      .then(setHosts)
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(load, [load]);

  const errMsg = (err: unknown) => (err instanceof ApiError ? err.message : String(err));

  async function create() {
    if (!label.trim() || !address.trim()) {
      setError("Label and address are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await endpoints.createHost({
        label: label.trim(),
        address: address.trim(),
        ssh_user: sshUser.trim() || undefined,
        os_type: osType || undefined,
      });
      setLabel("");
      setAddress("");
      setSshUser("");
      setOsType("");
      load();
    } catch (err) {
      setError(errMsg(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(host: Host) {
    if (!window.confirm(`Delete host "${host.label}" (${host.address})?`)) {
      return;
    }
    try {
      await endpoints.deleteHost(host.id);
      load();
    } catch (err) {
      setError(errMsg(err));
    }
  }

  return (
    <main className="page">
      <div className="sec-head">Catalog</div>
      <h1>Hosts</h1>
      <p className="page-sub">
        Your range's deployment targets. Save them once here, then pick them when deploying an
        agent instead of retyping hostnames each time.
      </p>

      {error && <div className="notice error">{error}</div>}

      <div className="form">
        <div className="field-row">
          <div className="field">
            <label htmlFor="host-label">Label</label>
            <input
              id="host-label"
              value={label}
              placeholder="Web 01"
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="host-address">Address</label>
            <input
              id="host-address"
              value={address}
              placeholder="web01.corp.local"
              onChange={(e) => setAddress(e.target.value)}
            />
          </div>
        </div>
        <div className="field-row">
          <div className="field">
            <label htmlFor="host-user">SSH user (optional)</label>
            <input
              id="host-user"
              value={sshUser}
              placeholder="operator"
              onChange={(e) => setSshUser(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="host-os">OS (optional)</label>
            <select id="host-os" value={osType} onChange={(e) => setOsType(e.target.value)}>
              <option value="">—</option>
              <option value="linux">linux</option>
              <option value="macos">macos</option>
              <option value="windows">windows</option>
            </select>
          </div>
        </div>
        <button className="btn primary" onClick={create} disabled={busy}>
          {busy ? "Adding…" : "Add host"}
        </button>
      </div>

      {hosts.length > 0 ? (
        <table className="table">
          <thead>
            <tr>
              <th>Label</th>
              <th>Address</th>
              <th>SSH user</th>
              <th>OS</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {hosts.map((host) => (
              <tr key={host.id}>
                <td>{host.label}</td>
                <td className="mono">{host.address}</td>
                <td>{host.ssh_user ?? "-"}</td>
                <td>{host.os_type ?? "-"}</td>
                <td className="row-actions">
                  <button className="btn small danger" onClick={() => remove(host)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="empty">No hosts yet. Add your range's machines above.</p>
      )}
    </main>
  );
}
