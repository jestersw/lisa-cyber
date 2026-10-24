"""End-to-end Windows build smoke test (#221).

Builds the agent through the real build pipeline (`build_agent`), runs the
produced .exe against a stub backend, and asserts the agent sends a heartbeat.
This is what the Windows CI job runs; it catches breakage that the unit tests
(which use a fake source tree) cannot, e.g. the source layout / import
resolution, the Windows toolchain, and that Nuitka's .exe actually runs and
talks to the backend.

Exits 0 on success, non-zero with a message otherwise. Intended for a Windows
runner with Nuitka installed; on a non-Windows host it exits 0 with a skip
note, since the build gate refuses cross-OS builds anyway.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.defaults import build_agent_config
from app.services.agent_builder import compiler
from app.services.agent_builder.builder import build_agent

AGENT_ID = "SMOKE001"
HEARTBEAT_TIMEOUT_S = 120

_heartbeats: list[dict] = []


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        if self.path == "/api/agents/heartbeat":
            try:
                _heartbeats.append(json.loads(body or b"{}"))
            except ValueError:
                _heartbeats.append({})
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")
        elif self.path.endswith("/enroll"):
            # Install-time enrollment (#201): hand back a real token so the agent
            # can then authenticate its heartbeat.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"agent_id": "SMOKE001", "token": "smoke-real-token"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:  # silence per-request logging
        pass


def _start_stub() -> tuple[socketserver.TCPServer, int]:
    server = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def main() -> int:
    if compiler.builder_os() != "windows":
        print(f"SKIP: builder_os={compiler.builder_os()} (Windows runner required)")
        return 0

    server, port = _start_stub()
    backend_url = f"http://127.0.0.1:{port}"
    token = "smoke-token"  # noqa: S105 - test-only token for the stub
    agent_config = build_agent_config(AGENT_ID, "Smoke", "developer", "windows", [], {})
    package = {"agent_config": agent_config, "application_plugins": {}}

    repo_root = Path(__file__).resolve().parents[2]
    agent_src = repo_root / "agent" / "lisa_agent"

    # ignore_cleanup_errors: a Nuitka onefile .exe can briefly keep its own file
    # open after we stop it, and Windows refuses to unlink an open file. We kill
    # the process tree below to release it; this is a belt-and-suspenders so a
    # residual lock can never turn a passing smoke into a teardown failure.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        print(f"building {AGENT_ID} for windows via build_agent() ...")
        result = build_agent(
            agent_id=AGENT_ID,
            deployment_package=package,
            agent_token=token,
            backend_url=backend_url,
            agent_source_root=agent_src,
            target_os="windows",
            workspace_root=tmp_path / "ws",
            storage_root=tmp_path / "stg",
        )
        if not result.success or result.artefacts is None:
            print("FAIL: build did not succeed")
            print(result.stderr[-4000:])
            return 1

        binary = result.artefacts.binary_path
        pkg_json = result.artefacts.package_path
        print(f"built {binary} ({binary.stat().st_size} bytes); running ...")

        env = {
            **os.environ,
            "LISA_BACKEND_URL": backend_url,
            "LISA_AGENT_TOKEN": token,
            "LISA_PACKAGE_PATH": str(pkg_json),
        }
        proc = subprocess.Popen([str(binary)], env=env)
        try:
            deadline = time.time() + HEARTBEAT_TIMEOUT_S
            while time.time() < deadline and not _heartbeats:
                if proc.poll() is not None:
                    print(f"FAIL: agent exited early with code {proc.returncode}")
                    return 1
                time.sleep(1)
        finally:
            # A Nuitka onefile launches a child process that holds the .exe
            # open; terminating only the parent leaves the file locked, which
            # then breaks temp-dir cleanup. taskkill /T kills the whole tree.
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            # Give Windows a moment to release the file handle before the
            # TemporaryDirectory context tries to delete the .exe.
            time.sleep(1)
            server.shutdown()

        if not _heartbeats:
            print(f"FAIL: no heartbeat received within {HEARTBEAT_TIMEOUT_S}s")
            return 1

        hb = _heartbeats[0]
        print(f"OK: heartbeat received from agent_id={hb.get('agent_id')}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
