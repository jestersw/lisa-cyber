import { useEffect, useState } from "react";
import { endpoints, type ApplicationTemplate } from "../api/client";

const ROLES = ["developer", "admin", "user"];
const OS_OPTIONS = ["linux", "macos", "windows"];
const WEEKDAYS = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 7, label: "Sun" },
];

export function AgentCreate() {
  const [name, setName] = useState("");
  const [role, setRole] = useState("developer");
  const [osType, setOsType] = useState("linux");
  const [applications, setApplications] = useState<string[]>([]);
  const [customApp, setCustomApp] = useState("");

  const [workdays, setWorkdays] = useState<number[]>([1, 2, 3, 4, 5]);
  const [workStart, setWorkStart] = useState("");
  const [workEnd, setWorkEnd] = useState("");
  const [lunchEarliest, setLunchEarliest] = useState("13:00");
  const [lunchLatest, setLunchLatest] = useState("15:00");
  const [lunchMin, setLunchMin] = useState(45);
  const [lunchMax, setLunchMax] = useState(75);

  const [sessionMin, setSessionMin] = useState(300);
  const [sessionMax, setSessionMax] = useState(900);
  const [switchMin, setSwitchMin] = useState(30);
  const [switchMax, setSwitchMax] = useState(120);
  const [inactiveMin, setInactiveMin] = useState(10);
  const [inactiveMax, setInactiveMax] = useState(20);

  const [heartbeatMinutes, setHeartbeatMinutes] = useState(30);

  const [available, setAvailable] = useState<ApplicationTemplate[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    endpoints
      .applicationTemplates()
      .then(setAvailable)
      .catch(() => setAvailable([]));
  }, []);

  const suggestions = available.filter((app) => app.os_type === osType);

  function toggleApp(appName: string) {
    setApplications((current) =>
      current.includes(appName)
        ? current.filter((item) => item !== appName)
        : [...current, appName],
    );
  }

  function addCustomApp() {
    const value = customApp.trim().toLowerCase();
    if (value && !applications.includes(value)) {
      setApplications((current) => [...current, value]);
    }
    setCustomApp("");
  }

  function toggleWorkday(day: number) {
    setWorkdays((current) =>
      current.includes(day)
        ? current.filter((item) => item !== day)
        : [...current, day].sort((a, b) => a - b),
    );
  }

  async function submit() {
    setError(null);
    setResult(null);
    if (!name.trim()) {
      setError("Agent name is required.");
      return;
    }
    if (applications.length === 0) {
      setError("Select at least one application.");
      return;
    }

    const payload: Record<string, unknown> = {
      name: name.trim(),
      role: role,
      os_type: osType,
      applications: applications,
      behavior: {
        session_duration: { min: sessionMin, max: sessionMax },
        app_switch_pause: { min: switchMin, max: switchMax },
        inactive_period: { min: inactiveMin, max: inactiveMax },
      },
      heartbeat_interval_minutes: heartbeatMinutes,
    };

    if (workStart && workEnd) {
      payload.schedule = {
        workdays: workdays,
        work_start: workStart,
        work_end: workEnd,
        lunch: {
          earliest: lunchEarliest,
          latest: lunchLatest,
          min_minutes: lunchMin,
          max_minutes: lunchMax,
        },
      };
    }

    setSubmitting(true);
    try {
      const response = await endpoints.generateAgent(payload);
      setResult(response.agent_id);
      setName("");
      setApplications([]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <div className="sec-head">New agent</div>
      <h1>Configure a pseudo-employee</h1>
      <p className="page-sub">
        Identity, schedule, behaviour and the apps this agent uses. Leave work hours blank and they
        are randomised once at generation time.
      </p>

      <div className="form">
        <div className="field">
          <label htmlFor="agent-name">Name</label>
          <input
            id="agent-name"
            value={name}
            placeholder="John Doe"
            onChange={(event) => setName(event.target.value)}
          />
        </div>

        <div className="field">
          <label htmlFor="agent-role">Role</label>
          <select id="agent-role" value={role} onChange={(event) => setRole(event.target.value)}>
            {ROLES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="agent-os">OS type</label>
          <select id="agent-os" value={osType} onChange={(event) => setOsType(event.target.value)}>
            {OS_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label>Applications</label>
          {suggestions.length > 0 && (
            <div className="app-list">
              {suggestions.map((app) => (
                <span
                  key={app.id}
                  className={`app-chip ${applications.includes(app.name) ? "selected" : ""}`}
                  onClick={() => toggleApp(app.name)}
                >
                  {app.name}
                </span>
              ))}
            </div>
          )}
          <div className="app-row">
            <input
              value={customApp}
              placeholder="discord"
              onChange={(event) => setCustomApp(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addCustomApp();
                }
              }}
            />
            <button className="btn" type="button" onClick={addCustomApp}>
              Add
            </button>
          </div>
          {applications.length > 0 && (
            <div className="app-list">
              {applications.map((app) => (
                <span key={app} className="app-chip selected" onClick={() => toggleApp(app)}>
                  {app} ×
                </span>
              ))}
            </div>
          )}
          <span className="field-hint">
            App names only. The backend delivers each plugin alongside the config.
          </span>
        </div>

        <div className="field">
          <label>Workdays</label>
          <div className="app-list">
            {WEEKDAYS.map((day) => (
              <span
                key={day.value}
                className={`app-chip ${workdays.includes(day.value) ? "selected" : ""}`}
                onClick={() => toggleWorkday(day.value)}
              >
                {day.label}
              </span>
            ))}
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="work-start">Work start</label>
            <input
              id="work-start"
              type="time"
              value={workStart}
              onChange={(event) => setWorkStart(event.target.value)}
            />
            <span className="field-hint">Blank = random 08:00-10:00</span>
          </div>
          <div className="field">
            <label htmlFor="work-end">Work end</label>
            <input
              id="work-end"
              type="time"
              value={workEnd}
              onChange={(event) => setWorkEnd(event.target.value)}
            />
            <span className="field-hint">Blank = random 17:00-19:00</span>
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="lunch-earliest">Lunch earliest</label>
            <input
              id="lunch-earliest"
              type="time"
              value={lunchEarliest}
              onChange={(event) => setLunchEarliest(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="lunch-latest">Lunch latest</label>
            <input
              id="lunch-latest"
              type="time"
              value={lunchLatest}
              onChange={(event) => setLunchLatest(event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="lunch-min">Min minutes</label>
            <input
              id="lunch-min"
              type="number"
              value={lunchMin}
              onChange={(event) => setLunchMin(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="lunch-max">Max minutes</label>
            <input
              id="lunch-max"
              type="number"
              value={lunchMax}
              onChange={(event) => setLunchMax(Number(event.target.value))}
            />
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="session-min">Session min (s)</label>
            <input
              id="session-min"
              type="number"
              value={sessionMin}
              onChange={(event) => setSessionMin(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="session-max">Session max (s)</label>
            <input
              id="session-max"
              type="number"
              value={sessionMax}
              onChange={(event) => setSessionMax(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="switch-min">Switch min (s)</label>
            <input
              id="switch-min"
              type="number"
              value={switchMin}
              onChange={(event) => setSwitchMin(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="switch-max">Switch max (s)</label>
            <input
              id="switch-max"
              type="number"
              value={switchMax}
              onChange={(event) => setSwitchMax(Number(event.target.value))}
            />
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="inactive-min">Inactive min (n)</label>
            <input
              id="inactive-min"
              type="number"
              value={inactiveMin}
              onChange={(event) => setInactiveMin(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="inactive-max">Inactive max (n)</label>
            <input
              id="inactive-max"
              type="number"
              value={inactiveMax}
              onChange={(event) => setInactiveMax(Number(event.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="heartbeat">Heartbeat (min)</label>
            <input
              id="heartbeat"
              type="number"
              value={heartbeatMinutes}
              onChange={(event) => setHeartbeatMinutes(Number(event.target.value))}
            />
          </div>
        </div>

        <button className="btn primary" onClick={submit} disabled={submitting}>
          {submitting ? "Creating..." : "Create agent"}
        </button>
      </div>

      {error && <div className="notice error">{error}</div>}
      {result && <div className="notice success">Agent created: {result}</div>}
    </main>
  );
}
