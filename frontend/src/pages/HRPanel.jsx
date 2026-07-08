// HR Panel - sees aggregated attendance/zone summaries only, never raw
// position coordinates or checkpoint photos (Section 7 data minimization).
export default function HRPanel() {
  return (
    <div style={{ padding: 24 }}>
      <h1>HR panel</h1>
      <p>Attendance derived from badge activity, zone time summaries, shift compliance.</p>
      <p style={{ color: "#888" }}>TODO: fetch from GET /api/hr/attendance-summary</p>
    </div>
  );
}
