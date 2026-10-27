import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { endpoints, type FleetAgent, type LiveEvent } from "../api/client";

const POLL_MS = 3000;
// How long after the last heartbeat we still consider an agent "online".
const FRESH_MS = 2 * 60 * 1000;
const MAX_FEED = 200;
// How many recent events the chain groups into app sessions.
const CHAIN_LEN = 80;
// Approx width (px) of one spine column incl. its gap; drives serpentine wrap.
const COL_W = 184;

// Map an activity type to a colour class. app_open/app_close/idle are the
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

// A plain-language description of one event, for the "now" strip and tooltips.
function describe(ev: LiveEvent): string {
  const detail = detailOf(ev);
  switch (ev.activity_type) {
    case "app_open":
      return `opened ${ev.app}`;
    case "app_close":
      return `closed ${ev.app}`;
    case "network":
      return `network request${detail ? ` → ${detail}` : ""}`;
    case "file":
      return `file ${detail ?? "activity"}`;
    case "input":
      return `typing in ${ev.app}`;
    case "idle":
      return "stepped away";
    default:
      return `${ev.activity_type} in ${ev.app}`;
  }
}

interface Branch {
  id: number;
  kind: string;
  detail: string | null;
}

interface Session {
  id: number;
  app: string;
  agent: string | null;
  time: string | null;
  branches: Branch[];
  closed: boolean;
}

// Fold the flat event stream into app sessions: an app_open starts a session,
// the activities inside it hang off as branches, and app_close ends it. This is
// what turns the chain from a flat line into a spine-with-branches.
function buildSessions(evs: LiveEvent[]): Session[] {
  const sessions: Session[] = [];
  let cur: Session | null = null;
  for (const ev of evs) {
    if (ev.activity_type === "app_open") {
      cur = { id: ev.id, app: ev.app, agent: ev.agent_id, time: ev.timestamp, branches: [], closed: false };
      sessions.push(cur);
    } else if (ev.activity_type === "app_close") {
      if (cur && cur.app === ev.app) {
        cur.closed = true;
        cur = null;
      }
    } else {
      const branch: Branch = { id: ev.id, kind: ev.activity_type, detail: detailOf(ev) };
      if (cur) {
        cur.branches.push(branch);
      } else {
        // Activity before we saw an open (chain starts mid-session): start a
        // loose session so nothing is dropped.
        cur = {
          id: ev.id,
          app: ev.app,
          agent: ev.agent_id,
          time: ev.timestamp,
          branches: [branch],
          closed: false,
        };
        sessions.push(cur);
      }
    }
  }
  return sessions;
}

function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let i = 0; i < items.length; i += size) rows.push(items.slice(i, i + size));
  return rows;
}

export function Range() {
  const [fleet, setFleet] = useState<FleetAgent[]>([]);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cols, setCols] = useState(6);
  const cursor = useRef<number | null>(null);
  const spineRef = useRef<HTMLDivElement | null>(null);

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

  // Recompute how many columns fit, so the chain wraps (down, then back) as the
  // window resizes instead of scrolling off to the right.
  useEffect(() => {
    const el = spineRef.current;
    if (!el) return;
    const update = () => setCols(Math.max(1, Math.floor(el.clientWidth / COL_W)));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Oldest -> newest. Keep the newest row in view as the chain grows downward.
  const sessions = buildSessions(events.slice(0, CHAIN_LEN).reverse());
  const newestId = sessions.length ? sessions[sessions.length - 1].id : null;
  const rows = chunk(sessions, cols);

  // "What's happening now": the latest event per online agent, so the operator
  // can read the current state as a sentence instead of decoding the chain.
  const latestByAgent = new Map<string, LiveEvent>();
  for (const ev of events) {
    if (ev.agent_id && !latestByAgent.has(ev.agent_id)) latestByAgent.set(ev.agent_id, ev);
  }
  const nowRows = fleet
    .filter((a) => isFresh(a.last_seen))
    .map((a) => ({ agent: a, last: latestByAgent.get(a.agent_id) ?? null }));

  useEffect(() => {
    const el = spineRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events, cols]);

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
        heartbeat, and a live chain of each action as it happens.
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

      <h2 className="section-title">What's happening now</h2>
      {nowRows.length === 0 ? (
        <p className="empty">No agent is active right now.</p>
      ) : (
        <ul className="now-strip">
          {nowRows.map(({ agent, last }) => (
            <li className="now-row" key={agent.agent_id}>
              <span className="now-dot" />
              <Link to={`/agents/${agent.agent_id}`} className="now-agent">
                {agent.agent_id}
              </Link>
              <span className="now-app">{agent.current_app ?? last?.app ?? "idle"}</span>
              <span className="now-doing">{last ? describe(last) : "waiting…"}</span>
              {last?.timestamp && <span className="now-time mono">{clock(last.timestamp)}</span>}
            </li>
          ))}
        </ul>
      )}

      <h2 className="section-title">Activity chain</h2>
      <p className="chain-hint">
        Each node is an app session; the actions inside it branch below. The chain fills a row,
        then drops down and runs back the other way. The highlighted node is where the agent is now.
      </p>
      <div className="spine" ref={spineRef}>
        {sessions.length === 0 ? (
          <p className="empty">Waiting for activity… the chain builds as agents open apps and work.</p>
        ) : (
          rows.map((row, r) => {
            // Serpentine: even rows run left→right, odd rows right→left, so the
            // chain snakes down the page instead of scrolling away.
            const reversed = r % 2 === 1;
            const cells = reversed ? [...row].reverse() : row;
            const turn = r === 0 ? "" : reversed ? " turn-right" : " turn-left";
            return (
              <div className={`spine-row${turn}`} key={r}>
                {r > 0 && <span className="spine-turn" />}
                {cells.map((s, i) => {
                  const current = s.id === newestId;
                  return (
                    <div className={`spine-col${current ? " newest" : ""}`} key={s.id}>
                      {i > 0 && <span className="spine-link" />}
                      {current && <span className="now-badge">● NOW</span>}
                      <div className="spine-node ev-open">
                        <span className="spine-glyph">▸</span>
                      </div>
                      <div className="spine-app" title={s.app}>
                        {s.app}
                      </div>
                      <div className="spine-sub">
                        {s.agent ?? "?"} · {clock(s.time)}
                        {!s.closed && <span className="spine-live"> · live</span>}
                      </div>
                      <div className="spine-branches">
                        {s.branches.length === 0 && (
                          <div className="branch empty-branch">no actions yet</div>
                        )}
                        {s.branches.map((b) => (
                          <div
                            className={`branch ${CATEGORY_CLASS[b.kind] ?? "ev-process"}`}
                            key={b.id}
                          >
                            <span className="branch-dot" />
                            <span className="branch-kind">{b.kind}</span>
                            {b.detail && <span className="branch-detail">{b.detail}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })
        )}
      </div>

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
