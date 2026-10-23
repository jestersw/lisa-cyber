import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { endpoints } from "../api/client";

const links = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/agents", label: "Agents" },
  { to: "/agents/create", label: "New agent" },
];

export function Layout() {
  const navigate = useNavigate();

  function logout() {
    endpoints.logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app-shell">
      <nav className="nav">
        <div className="wordmark">
          <span className="dot" />
          Living Infrastructure Simulator Agent
        </div>
        <div className="nav-links">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === "/agents"}
              className={({ isActive }) => (isActive ? "active" : "")}
            >
              {link.label}
            </NavLink>
          ))}
          <button type="button" className="logout" onClick={logout}>
            Sign out
          </button>
        </div>
      </nav>
      <Outlet />
    </div>
  );
}
