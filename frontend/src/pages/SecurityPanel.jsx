// Security/Admin Panel - highest privilege, full live map + checkpoint
// photos + full audit log. Every view of this panel is logged against
// this role specifically (Section 7) - the broad access is offset by the
// heaviest audit logging, never by having none.
export default function SecurityPanel() {
  return (
    <div style={{ padding: 24 }}>
      <h1>Security / admin panel</h1>
      <p>Full live map, alerts, checkpoint photos, full audit log.</p>
      <p style={{ color: "#888" }}>TODO: live map component (Leaflet), alert feed, checkpoint viewer</p>
    </div>
  );
}
