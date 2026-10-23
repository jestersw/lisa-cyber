import { Navigate, Outlet, useLocation } from "react-router-dom";
import { isAuthenticated } from "../api/client";

/** Gate panel routes: send unauthenticated visitors to the login screen,
 * remembering where they were headed so login can return them there. */
export function ProtectedRoute() {
  const location = useLocation();
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
