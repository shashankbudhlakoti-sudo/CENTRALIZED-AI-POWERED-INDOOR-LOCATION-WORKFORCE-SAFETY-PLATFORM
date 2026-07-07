// Finance Panel - sees asset/cost data only, zero employee location data
// of any kind (Section 7).
export default function FinancePanel() {
  return (
    <div style={{ padding: 24 }}>
      <h1>Finance panel</h1>
      <p>Hardware asset inventory, cost tracking, tag replacement/procurement records.</p>
      <p style={{ color: "#888" }}>TODO: fetch from GET /api/finance/assets</p>
    </div>
  );
}
