import { useEffect, useRef } from "react";

/**
 * The rotating 3D "code drum" from the mockup: ten panels arranged in a
 * cylinder, each filled with rows of pseudo-code that periodically pulse
 * (rewrite themselves + brief highlight). Vanilla CSS 3D + DOM writes; no
 * canvas, no libraries.
 *
 * Ported from docs/design/panel-mockup.html. Kept close to the original so the
 * visual matches exactly.
 */

const PANELS = 12;
const ROWS = 26;
const W = 230;
const PULSE_MS = 130;

const TOKENS = [
  "agent.tick()",
  "user.behave()",
  "inject(pid)",
  "mem.write",
  "proc.mask()",
  "cyber.range",
  "dropper.run",
  "01001101",
  "ρ·load",
  "ldap.bind()",
  "keycloak.oidc",
  "seed_users()",
  "detect?",
  "log.event",
  "0x",
  "ssh :22",
  "payload()",
  "→ node",
  "spawn()",
  "mask.proc",
  "token.issue",
  "peaceful.bg",
  "noise++",
  "validate()",
];

function hex(n: number): string {
  let s = "";
  for (let i = 0; i < n; i++) {
    s += "0123456789abcdef"[(Math.random() * 16) | 0];
  }
  return s;
}

function line(): string {
  const parts: string[] = [];
  let len = 0;
  while (len < 26) {
    const t =
      Math.random() < 0.25
        ? "0x" + hex(4)
        : TOKENS[(Math.random() * TOKENS.length) | 0];
    parts.push(t);
    len += t.length + 1;
  }
  return parts.join(" ").slice(0, 30);
}

export function CodeDrum() {
  const drumRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const drum = drumRef.current;
    if (!drum) {
      return;
    }
    // Users who ask their OS to reduce motion get a static drum.
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const radius = Math.round(W / 2 / Math.tan(Math.PI / PANELS));

    // Build the panels once. React would over-manage this, so we go DOM-direct
    // inside a ref — same pattern as canvas animations.
    const rowsByPanel: HTMLDivElement[][] = [];
    for (let p = 0; p < PANELS; p++) {
      const panel = document.createElement("div");
      panel.className = "drum-panel";
      panel.style.transform = `rotateY(${p * (360 / PANELS)}deg) translateZ(${radius}px)`;
      const rows: HTMLDivElement[] = [];
      for (let r = 0; r < ROWS; r++) {
        const row = document.createElement("div");
        row.className = "drum-row";
        row.textContent = line();
        panel.appendChild(row);
        rows.push(row);
      }
      rowsByPanel.push(rows);
      drum.appendChild(panel);
    }

    let timer: number | undefined;
    if (!reduce) {
      timer = window.setInterval(() => {
        for (let p = 0; p < PANELS; p++) {
          const rows = rowsByPanel[p];
          for (let k = 0; k < 3; k++) {
            const row = rows[(Math.random() * rows.length) | 0];
            row.textContent = line();
            row.classList.remove("off");
            row.classList.add("hot");
            setTimeout(() => row.classList.remove("hot"), 220);
          }
          rows[(Math.random() * rows.length) | 0].classList.toggle("off");
        }
      }, PULSE_MS);
    }

    return () => {
      if (timer) {
        window.clearInterval(timer);
      }
      // Remove every panel we created. Without this StrictMode / HMR would
      // stack drums on top of each other.
      while (drum.firstChild) {
        drum.removeChild(drum.firstChild);
      }
    };
  }, []);

  return (
    <div className="stage" aria-hidden="true">
      <div className="drum" ref={drumRef} />
    </div>
  );
}
