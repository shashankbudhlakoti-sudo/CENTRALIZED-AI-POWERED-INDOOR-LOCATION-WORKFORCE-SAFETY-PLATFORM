// General Manager dashboard - Tier 4, organizational visibility
// (department summaries, manager directory) rather than Security's
// operational visibility (exact coordinates, live map) - Section 11.
export default function ManagerDashboard() {
  return (
    <div style={{ padding: 24 }}>
      <h1>Manager dashboard</h1>
      <p>All-department summaries and manager directory with drill-in access.</p>
      <p style={{ color: "#888" }}>TODO: fetch from GET /api/manager/department-summaries</p>
    </div>
  );
}
