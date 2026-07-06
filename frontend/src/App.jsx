import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { initAuth, getRoles, logout } from "./auth/keycloak";
import ITPanel from "./pages/ITPanel";
import HRPanel from "./pages/HRPanel";
import FinancePanel from "./pages/FinancePanel";
import SecurityPanel from "./pages/SecurityPanel";
import ManagerDashboard from "./pages/ManagerDashboard";
const ROLE_HOME = {
  it_manager: "/it",
  hr_manager: "/hr",
  finance_manager: "/finance",
  security_admin: "/security",
  general_manager: "/manager",
};
export default function App() {
  const [ready, setReady] = useState(false);
  const [homePath, setHomePath] = useState(null);
  useEffect(() => {
    initAuth().then((authenticated) => {
      if (!authenticated) return;
      const roles = getRoles();
      const landing = Object.entries(ROLE_HOME).find(([role]) => roles.includes(role));
      setHomePath(landing ? landing[1] : "/no-access");
      setReady(true);
    });
  }, []);
  if (!ready) {
    return <div style={{ padding: 24 }}>Signing you in...</div>;
  }
  return (
    <BrowserRouter>
      <header style={{ display: "flex", justifyContent: "flex-end", padding: 12 }}>
        <button onClick={logout}>Sign out</button>
      </header>
      <Routes>
        <Route path="/" element={<Navigate to={homePath} replace />} />
        <Route path="/it" element={<ITPanel />} />
        <Route path="/hr" element={<HRPanel />} />
        <Route path="/finance" element={<FinancePanel />} />
        <Route path="/security" element={<SecurityPanel />} />
        <Route path="/manager" element={<ManagerDashboard />} />
        <Route path="/no-access" element={<div style={{ padding: 24 }}>Your account has no dashboard access assigned. Contact your administrator.</div>} />
      </Routes>
    </BrowserRouter>
  );
}
