import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import "../styles/landing.css";

// Simple project cards for the Projects section. In the mockup thumbnails are
// procedurally generated SVGs — we'll wire that up in a later PR; for now
// each card has a solid gradient thumbnail so the section already looks
// intentional.
const PROJECTS = [
  {
    label: "LISA Core — ML & AI",
    desc: "We've extended LISA with machine learning and AI to make agent behavior more lifelike and adaptive.",
    gradient: "linear-gradient(135deg, #03365B, #01669C)",
  },
  {
    label: "Backend",
    desc: "Configuration and control center for the whole system.",
    gradient: "linear-gradient(135deg, #122538, #03365B)",
  },
  {
    label: "Frontend",
    desc: "Admin panel built with React and TypeScript.",
    gradient: "linear-gradient(135deg, #03365B, #122538)",
  },
  {
    label: "Linux Agent",
    desc: "In-memory agent reproducing believable user activity on Linux.",
    gradient: "linear-gradient(135deg, #01669C, #03365B)",
  },
  {
    label: "Windows Agent",
    desc: "The same lifelike behavior, on Windows.",
    gradient: "linear-gradient(135deg, #122538, #01669C)",
  },
  {
    label: "Planned — Suspicious activity",
    desc: "Next, we're teaching our agents to reproduce suspicious and adversarial behavior, so detection training reaches beyond peaceful background noise.",
    gradient: "linear-gradient(135deg, #01669C, #9BBACD)",
    planned: true,
  },
];

export function LandingPage() {
  const navigate = useNavigate();

  // Enter key on the landing page also enters the panel. Nothing else on this
  // page listens to Enter, so this is safe.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Enter") {
        navigate("/dashboard");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  const enterPanel = () => navigate("/dashboard");

  return (
    <div className="landing">
      <nav className="landing-nav">
        <div className="wordmark">
          <span className="dot" />
          Living Infrastructure Simulator Agent
        </div>
        <div className="nav-links">
          <a className="explore" href="#about">
            Explore
          </a>
        </div>
      </nav>

      <header className="hero">
        <div className="hero-inner">
          <div className="eyebrow">An independent simulation lab</div>
          <h1>
            Living Infrastructure
            <br />
            Simulator Agent
          </h1>
          <div className="decoded">
            Simulating lifelike user activity inside isolated cyber-range infrastructure.
          </div>
          <button className="enter" onClick={enterPanel} type="button">
            Enter <span className="arw">→</span>
          </button>
        </div>
      </header>

      <section className="block" id="about">
        <div className="sec-head">About</div>
        <h2>
          We build agents that behave like real people — so defenders can train against the
          real thing.
        </h2>
        <p>
          LISA simulates realistic user behavior inside an isolated cyber-range training
          infrastructure. It generates a believable background of everyday, "peaceful"
          activity, so security teams can practice threat detection and incident analysis
          in conditions close to the real world. Our multi-platform agents run on Linux
          and Windows and operate entirely in memory — no disk footprint, process
          masquerading, and graceful cleanup — with loosely coupled, well-documented
          components. Open source, MIT-licensed.
        </p>
      </section>

      <section className="block" id="projects">
        <div className="sec-head">Projects</div>
        <h2>What we're building on GitHub.</h2>
        <p className="intro">
          A small but growing set of open-source repositories under the LISA organization.
        </p>
        <div className="proj-grid">
          {PROJECTS.map((p) => (
            <div key={p.label} className={`proj${p.planned ? " planned" : ""}`}>
              {p.planned && <span className="badge">Planned</span>}
              <div className="thumb" style={{ background: p.gradient }} />
              <div className="pinfo">
                <div className="plabel">{p.label}</div>
                <div className="pdesc">{p.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="block" id="careers">
        <div className="sec-head">Careers</div>
        <h2>We're a lean, self-funded, distributed team and we're always hiring.</h2>
        <p>Help us build and explore new infrastructure to amplify the human spirit.</p>
      </section>

      <section className="block" id="contact">
        <div className="sec-head">Contact</div>
        <h2>Get in touch.</h2>
        <div className="contact-lines">
          <div>
            For product questions and support, reach us on <b>Discord</b> or our{" "}
            <b>help page</b>.
          </div>
          <div>
            For billing support, email <b>billing@lisa.sim</b>
          </div>
          <div>
            For journalistic inquiries: <b>press@lisa.sim</b>
          </div>
        </div>
      </section>

      <footer className="landing-footer">
        <span>© 2026 Living Infrastructure Simulator Agent</span>
        <span>Terms · Privacy · Settings</span>
      </footer>
    </div>
  );
}
