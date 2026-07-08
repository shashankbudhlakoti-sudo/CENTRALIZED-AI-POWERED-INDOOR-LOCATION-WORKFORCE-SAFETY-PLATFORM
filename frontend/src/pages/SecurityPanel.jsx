// Security/Admin Panel - highest privilege, full live map + checkpoint
// photos + full audit log. Every view of this panel is logged against
// this role specifically (Section 7) - the broad access is offset by the
// heaviest audit logging, never by having none.
import LiveMap from "../components/LiveMap";
import { getToken } from "../auth/keycloak";

export default function SecurityPanel() {
  return (
    <div style={{ padding: 24, height: "100vh", display: "flex", flexDirection: "column" }}>
      <h1>Security / admin panel</h1>
      <p>Full live map, alerts, checkpoint photos, full audit log.</p>
      <div style={{ flex: 1, minHeight: 0 }}>
        <LiveMap
          wsUrl="ws://localhost:8000/ws"
          restUrl="http://localhost:8000/api/v1/positions/latest"
          authToken={getToken()}
        />
      </div>
      <p style={{ color: "#888" }}>TODO: alert feed, checkpoint viewer</p>
    </div>
  );
}
