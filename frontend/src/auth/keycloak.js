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

export default keycloak;
