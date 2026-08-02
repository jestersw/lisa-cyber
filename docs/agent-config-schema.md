# LISA Agent Configuration Specification

Owner: agent side. This document defines how a LISA agent is configured. The
agent config and application plugin formats below are the source of truth; the
backend stores and serves this JSON, and its agent-config endpoint must return
exactly this shape.

It defines:

1. the **agent config** (one pseudo-employee: identity, schedule, behaviour, and
   the list of apps they use);
2. the **application plugin** format (one app: how to install, open, and act);
3. the **deployment package** the agent receives (config + the plugins it needs);
4. **default-filling rules** applied when the user leaves fields blank.

---

## 1. Agent config

Describes a single pseudo-employee. Produced on the frontend from minimal user
input, then completed with defaults (section 4) before being stored and served
to the agent.

```json
{
  "agent_info": {
    "agent_id": "USR0012345",
    "name": "John Doe",
    "role": "developer",
    "os_type": "linux"
  },
  "schedule": {
    "workdays": [1, 2, 3, 4, 5],
    "work_start": "09:12",
    "work_end": "18:03",
    "lunch": {
      "earliest": "13:00",
      "latest": "15:00",
      "min_minutes": 45,
      "max_minutes": 75
    }
  },
  "behavior": {
    "session_duration": { "min": 300, "max": 900 },
    "app_switch_pause": { "min": 30, "max": 120 },
    "inactive_period": { "min": 10, "max": 20 }
  },
  "heartbeat": { "interval_minutes": 30 },
  "applications": ["discord", "vscode", "firefox"],
  "transition_model": {
    "version": 1,
    "trained_on": "role:developer",
    "counts": {
      "vscode":   { "terminal": 45, "firefox": 20, "vscode": 30 },
      "firefox":  { "slack": 30, "firefox": 25, "mail": 15 },
      "terminal": { "vscode": 40, "terminal": 30, "firefox": 20 }
    }
  }
}
```

### Field notes

- `agent_info.role` — one of `developer`, `admin`, `user`.
- `agent_info.os_type` — `linux` or `windows`.
- `schedule.workdays` — ISO weekdays, 1=Mon … 7=Sun.
- `schedule.work_start` / `work_end` — `HH:MM`, local time. Produced by the
  default-filler (section 4) when the user leaves them blank.
- `schedule.lunch` — the window and length bounds; the exact daily start and
  length are randomised by the agent at runtime within this window.
- `behavior.*` — ranges the agent draws from at runtime.
- `heartbeat.interval_minutes` — how often the agent reports status, in
  **minutes** (default 30).
- `applications` — a list of app **names**. The full plugin for each name is
  delivered alongside the config (section 3), not fetched separately.
- `transition_model` — **optional**. A markov model of app-to-app transitions
  used to pick the next application. Format matches `MarkovModel.to_dict()` on
  the backend: `{"version": 1, "counts": {current_app: {next_app: count, ...}}}`.
  If present, the agent picks the next app by sampling the transition
  distribution from the current one. If absent, the agent falls back to
  uniform random choice.
  An optional `trained_on` field marks the origin of the model (`role:developer`,
  `role:admin`, `shared`, ...) — set by the backend so operators can tell
  role-specific models from the shared fallback when debugging. The agent
  ignores this field; only `counts` affects behaviour.

---

## 2. Application plugin

Describes a single application: how to install it if missing, how to open/close
it, and what activities it performs (the `app_template.json` format). One plugin
per application.

```json
{
  "app_info": {
    "name": "discord",
    "display_name": "Discord Desktop",
    "category": "communication"
  },
  "installation": {
    "check_command": "discord --version",
    "install_method": "deb",
    "install_commands": ["..."],
    "post_install_commands": ["..."],
    "dependencies": ["xdotool"]
  },
  "execution": {
    "open_command": "discord",
    "close_command": "pkill -f discord",
    "window_class": "discord",
    "startup_delay": 8
  },
  "activities": [
    {
      "id": "check_servers",
      "name": "Check Servers",
      "weight": 35,
      "min_duration": 15,
      "max_duration": 45,
      "commands": [
        { "type": "key_combination", "keys": "ctrl+k", "delay": 1 },
        { "type": "type_text", "text": "general", "delay": 2 }
      ],
      "conditions": { "requires_activity": "open_app" }
    }
  ],
  "settings": {
    "usage_probability": 0.8,
    "work_hours_only": true
  }
}
```

### Command types (inside `activities[].commands`)

| type              | fields          | meaning                       |
|-------------------|-----------------|-------------------------------|
| `key`             | `key`, `delay`  | press a single key            |
| `key_combination` | `keys`, `delay` | press a chord (e.g. `ctrl+s`) |
| `type_text`       | `text`, `delay` | type a string                 |

`weight` biases random activity selection; `min/max_duration` bound how long an
activity runs.

### Design note (from the customer)

SOC analysts only see **OS-level** events (process start/stop, file, network,
auth) — not the *contents* of what's typed. Keep activities focused on producing
realistic process/file/network events; don't over-engineer keystroke detail that
no monitoring tool would ever see.

---

## 3. Deployment package (what the agent receives)

The backend delivers the agent config **and** the full plugin for every app in
`applications`, in one payload. The agent does not make a separate request per
app — everything needed arrives together (the target VM may be network-isolated).

```json
{
  "agent_config": { "...section 1..." },
  "application_plugins": {
    "discord": { "...section 2..." },
    "vscode":  { "...section 2..." },
    "firefox": { "...section 2..." }
  }
}
```

The agent builds an in-memory map `{name: plugin}` and, when its config says
"use discord", looks the plugin up by name.

### Missing-plugin rule

If `applications` names an app that has no entry in `application_plugins`, the
agent logs a warning and skips that app — it must not crash.

---

## 4. Default-filling rules

Applied when the user leaves fields blank, before the config is stored/served.

- **Work hours, if blank:** randomised once, at generation time (not daily), so
  each agent has stable but individual hours:
  - `work_start` ∈ 08:00–10:00
  - `work_end` ∈ 17:00–19:00
- **Lunch:** window defaults to 13:00–15:00, length 45–75 minutes. The exact
  daily start and length are randomised by the agent at runtime.
- **behavior blocks, if blank:**
  - `session_duration`: 300–900 s
  - `app_switch_pause`: 30–120 s
  - `inactive_period`: every 10–20 activity cycles
- **heartbeat.interval_minutes, if blank:** 30.
- **workdays, if blank:** Mon–Fri (`[1, 2, 3, 4, 5]`).
- **transition_model, if absent:** no default — the agent falls back to uniform
  random choice between applications.

---

## 5. Application plugin source

When resolving an app name to a plugin: use a pre-made plugin if one exists,
otherwise generate it (LLM/MCP). Either way the result conforms to section 2.
