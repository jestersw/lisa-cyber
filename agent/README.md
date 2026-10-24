# LISA agent

Activity-simulation agent. One codebase for **Linux, macOS and Windows**; the
only platform-specific bits live in `lisa_agent/platform_ops.py` (OS detection
and "open" command), with the per-OS translations funnelled through it:

- **keystrokes** — `xdotool` (Linux), `osascript`/System Events (macOS),
  PowerShell `SendKeys` (Windows), in `activity.py`;
- **network / file activity** — POSIX tools on Linux/macOS, PowerShell cmdlets
  on Windows, also in `activity.py`;
- **single-instance mutex** — flock + POSIX signals on Linux/macOS, a named
  Win32 mutex + `taskkill` on Windows, in `mutex.py`.

```bash
pip install -e '.[dev]'
lisa-agent          # run
pytest              # test
```

Note: building a standalone binary with Nuitka is per-host (Nuitka can't
cross-compile), so each OS target is built on a runner of that OS. The Windows
PE build runner is tracked separately; this package is the agent's runtime.
