import Keycloak from "keycloak-js";

const keycloakConfig = {
  url: "http://localhost:8080",
  realm: "safety-platform",
  clientId: "dashboard-frontend",
};

const keycloak = new Keycloak(keycloakConfig);
let isInitialized = false;
let initPromise = null;

export const initAuth = () => {
  if (isInitialized) return initPromise;
  
  if (!initPromise) {
    initPromise = keycloak.init({
      onLoad: "login-required",
      checkLoginIframe: false,
      pkceMethod: "S256"
    }).then((authenticated) => {
      isInitialized = true;
      if (authenticated) {
        console.log("Token claims:", keycloak.tokenParsed);
      }
      return authenticated;
    }).catch((err) => {
      initPromise = null;
      console.error("Keycloak initialization failed:", err);
      throw err;
    });
  }
  
  return initPromise;
};

// Required helper utilities imported by App, apiClient, and SecurityPanel
export const getToken = () => {
  return keycloak.token || "";
};

export const getRoles = () => {
  return keycloak.tokenParsed?.realm_access?.roles || [];
};

export const logout = () => {
  isInitialized = false;
  initPromise = null;
  keycloak.logout({ redirectUri: window.location.origin });
};

export default keycloak;
