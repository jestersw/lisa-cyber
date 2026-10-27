import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { endpoints, type FleetAgent, type LiveEvent } from "../api/client";

const POLL_MS = 3000;
// How long after the last heartbeat we still consider an agent "online".
const FRESH_MS = 2 * 60 * 1000;
const MAX_FEED = 200;

// Map an activity type to a feed colour class. app_open/app_close/idle are the
// lifecycle events; the rest are the OS-level categories the agent reports.
const CATEGORY_CLASS: Record<string, string> = {
  network: "ev-network",
  file: "ev-file",
  input: "ev-input",
  process: "ev-process",
  app_open: "ev-open",
  app_close: "ev-close",
  idle: "ev-idle",
};

function isFresh(lastSeen: string | null): boolean {
  if (!lastSeen) return false;
  return Date.now() - new Date(lastSeen).getTime() < FRESH_MS;
}

function ago(ts: string | null): string {
  if (!ts) return "never";
  const secs = Math.max(0, Math.round((Date.now() - new Date(ts).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}

function clock(ts: string | null): string {
  if (!ts) return "--:--:--";
  return new Date(ts).toLocaleTimeString();
}

function detailOf(ev: LiveEvent): string | null {
  const ctx = ev.context;
  if (!ctx) return null;
  if (typeof ctx.detail === "string") return ctx.detail;
  if (typeof ctx.activity === "string") return ctx.activity;
  if (typeof ctx.reason === "string") return ctx.reason;
  return null;
}

export function Range() {
  const [fleet, setFleet] = useState<FleetAgent[]>([]);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cursor = useRef<number | null>(null);

  const poll = useCallback(() => {
    endpoints
      .liveFleet()
      .then((r) => setFleet(r.agents))
      .catch((err: Error) => setError(err.message));
    endpoints
      .liveEvents(cursor.current)
      .then((r) => {
        if (r.latest_id != null) cursor.current = r.latest_id;
        if (r.events.length > 0) {
          // The feed returns newest-first; prepend and cap.
          setEvents((prev) => [...r.events, ...prev].slice(0, MAX_FEED));
        }
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => clearInterval(timer);
  }, [poll]);

  const online = fleet.filter((a) => isFresh(a.last_seen)).length;

  return (
    <main className="page">
      <div className="sec-head">Live</div>
      <div className="range-head">
        <h1>Range map</h1>
        <span className="live-badge">
          <span className="live-dot" />
          live · {online}/{fleet.length} online
        </span>
      </div>
      <p className="page-sub">
        Every agent on the range and what it's doing right now — current app from the latest
        heartbeat, and a live feed of each action as it happens.
      </p>

      {error && <div className="notice error">{error}</div>}

      {fleet.length === 0 ? (
        <p className="empty">No agents yet. Create and deploy one to see it light up here.</p>
      ) : (
        <div className="range-grid">
          {fleet.map((a) => {
            const fresh = isFresh(a.last_seen);
            return (
              <Link
                key={a.agent_id}
                to={`/agents/${a.agent_id}`}
                className={`range-cell${fresh ? " fresh" : " stale"}`}
              >
                <div className="range-cell-top">
                  <span className={`status-dot${fresh ? " on" : " off"}`} />
                  <span className="range-id">{a.agent_id}</span>
                  <span className="range-os">{a.os_type}</span>
                </div>
                <div className="range-app">{fresh ? (a.current_app ?? "idle") : "—"}</div>
                <div className="range-meta">
                  <span>{a.role ?? "no role"}</span>
                  <span>{ago(a.last_seen)}</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <h2 className="section-title">Activity feed</h2>
      {events.length === 0 ? (
        <p className="empty">Waiting for activity… agents report as they open apps and work.</p>
      ) : (
        <ul className="feed">
          {events.map((ev) => {
            const detail = detailOf(ev);
            return (
              <li key={ev.id} className="feed-row">
                <span className="feed-time mono">{clock(ev.timestamp)}</span>
                <span className="feed-agent">{ev.agent_id ?? "?"}</span>
                <span className={`feed-type ${CATEGORY_CLASS[ev.activity_type] ?? "ev-process"}`}>
                  {ev.activity_type}
                </span>
                <span className="feed-app">{ev.app}</span>
                {detail && <span className="feed-detail mono">{detail}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
