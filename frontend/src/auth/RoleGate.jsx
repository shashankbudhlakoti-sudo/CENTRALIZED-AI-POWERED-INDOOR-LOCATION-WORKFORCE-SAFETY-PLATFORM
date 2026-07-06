// Client-side role gating is a UX convenience only - it hides UI the user
// isn't meant to see. It is NEVER the security boundary; the backend's
// row-level security (Section 7) is what actually prevents data access.
// A user who forces this component to render still gets nothing back from
// the API if their JWT role doesn't authorize it.
import { hasRole } from "./keycloak";

export default function RoleGate({ role, children, fallback = null }) {
  if (!hasRole(role)) {
    return fallback;
  }
  return children;
}
