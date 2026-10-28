import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { endpoints, type FleetAgent, type LiveEvent } from "../api/client";

const POLL_MS = 3000;
// How long after the last heartbeat we still consider an agent "online".
const FRESH_MS = 2 * 60 * 1000;
const MAX_FEED = 200;
// How many recent events the chain shows.
const CHAIN_LEN = 60;
// Approx width (px) of one chain step incl. its gap; drives the serpentine wrap.
const COL_W = 148;

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

// A compact glyph per category so each step reads at a glance.
const CATEGORY_GLYPH: Record<string, string> = {
  network: "↗",
  file: "▤",
  input: "⌨",
  process: "⚙",
  app_open: "▸",
  app_close: "▪",
  idle: "‖",
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

function chunk<T>(items: T[], size: number): T[][] {
  const rows: T[][] = [];
  for (let i = 0; i < items.length; i += size) rows.push(items.slice(i, i + size));
  return rows;
}

// One agent's chain: a flowing line of its events that wraps serpentine-style
// (left→right, drop down, right→left) so a busy agent stays on screen. Each
// lane auto-scrolls to its own newest row.
function ChainLane({ events, cols }: { events: LiveEvent[]; cols: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const newestId = events.length ? events[events.length - 1].id : null;
  const rows = chunk(events, cols);

  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length, cols]);

  return (
    <div className="chain" ref={ref}>
      {rows.map((row, r) => {
        const reversed = r % 2 === 1;
        const cells = reversed ? [...row].reverse() : row;
        const turn = r === 0 ? "" : reversed ? " turn-right" : " turn-left";
        return (
          <div className={`chain-row${turn}`} key={r}>
            {r > 0 && <span className="chain-turn" />}
            {cells.map((ev, i) => {
              const detail = detailOf(ev);
              const cls = CATEGORY_CLASS[ev.activity_type] ?? "ev-process";
              return (
                <div className={`chain-step${ev.id === newestId ? " newest" : ""}`} key={ev.id}>
                  {i > 0 && <span className="chain-link" />}
                  <div className={`chain-node ${cls}`}>
                    <span className="chain-glyph">{CATEGORY_GLYPH[ev.activity_type] ?? "•"}</span>
                  </div>
                  <div className="chain-label">
                    <span className="chain-app">{ev.app}</span>
                    <span className="chain-kind">{ev.activity_type}</span>
                    {detail && <span className="chain-detail">{detail}</span>}
                    <span className="chain-who">{clock(ev.timestamp)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

export function Range() {
  const [fleet, setFleet] = useState<FleetAgent[]>([]);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [cols, setCols] = useState(6);
  const cursor = useRef<number | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);

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

  // Recompute how many columns fit, so each lane wraps (down, then back) as the
  // window resizes instead of scrolling off to the right.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const update = () => setCols(Math.max(1, Math.floor(el.clientWidth / COL_W)));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Group the stream into one chain per agent. `events` is newest-first; take up
  // to CHAIN_LEN per agent, then reverse to chronological for the lane. Order
  // lanes by most-recent activity so the busiest agents are on top.
  const byAgent = new Map<string, LiveEvent[]>();
  for (const ev of events) {
    if (!ev.agent_id) continue;
    const list = byAgent.get(ev.agent_id);
    if (list) {
      if (list.length < CHAIN_LEN) list.push(ev);
    } else {
      byAgent.set(ev.agent_id, [ev]);
    }
  }
  const fleetById = new Map(fleet.map((a) => [a.agent_id, a]));
  const lanes = [...byAgent.entries()]
    .sort((a, b) => (b[1][0]?.id ?? 0) - (a[1][0]?.id ?? 0))
    .map(([id, list]) => ({ id, agent: fleetById.get(id) ?? null, chain: [...list].reverse() }));

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

      <h2 className="section-title">Activity chains</h2>
      <div className="chains" ref={wrapRef}>
        {lanes.length === 0 ? (
          <p className="empty">Waiting for activity… a chain appears per agent as they act.</p>
        ) : (
          lanes.map(({ id, agent, chain }) => {
            const fresh = agent ? isFresh(agent.last_seen) : false;
            return (
              <section className="lane" key={id}>
                <div className="lane-head">
                  <span className={`status-dot${fresh ? " on" : " off"}`} />
                  <Link to={`/agents/${id}`} className="lane-id">
                    {id}
                  </Link>
                  {agent?.role && <span className="lane-role">{agent.role}</span>}
                  <span className="lane-app">{fresh ? (agent?.current_app ?? "idle") : "offline"}</span>
                </div>
                <ChainLane events={chain} cols={cols} />
              </section>
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
