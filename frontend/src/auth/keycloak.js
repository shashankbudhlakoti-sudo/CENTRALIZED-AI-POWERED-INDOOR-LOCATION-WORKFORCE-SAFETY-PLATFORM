// Keycloak integration.
//
// Security notes:
// - Uses the "authorization code + PKCE" flow (Keycloak-js default), never
//   the implicit flow - tokens are not exposed in the URL fragment history.
// - The token is kept in memory only (module-level variable), never in
//   localStorage/sessionStorage. Storing JWTs in browser storage makes them
//   readable by any XSS payload; keeping them in memory limits exposure to
//   the current page load.
// - Silent token refresh runs on a timer so the user is never holding an
//   expired token that a compromised extension could replay after expiry.
import Keycloak from "keycloak-js";

const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL,
  realm: import.meta.env.VITE_KEYCLOAK_REALM,
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID,
});

let refreshTimer = null;

export async function initAuth() {
  const authenticated = await keycloak.init({
    onLoad: "login-required",
    pkceMethod: "S256",
    checkLoginIframe: false,
  });

  if (authenticated) {
    scheduleRefresh();
  }

  return authenticated;
}

function scheduleRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  // Refresh when the token is within 60s of expiry, checked every 20s.
  refreshTimer = setInterval(async () => {
    try {
      await keycloak.updateToken(60);
    } catch {
      // Refresh failed - force re-login rather than continuing with a
      // stale/expired session.
      keycloak.login();
    }
  }, 20000);
}

export function getToken() {
  return keycloak.token;
}

export function getRoles() {
  return keycloak.tokenParsed?.realm_access?.roles ?? [];
}

export function hasRole(role) {
  return getRoles().includes(role);
}

export function logout() {
  if (refreshTimer) clearInterval(refreshTimer);
  keycloak.logout();
}

export default keycloak;
