// IT Panel - Section 7: sees device/system health only, never employee
// identity tied to positions (device IDs only).
export default function ITPanel() {
  return (
    <div style={{ padding: 24 }}>
      <h1>IT panel</h1>
      <p>Beacon/gateway health, tag battery status, system uptime, network diagnostics.</p>
      <p style={{ color: "#888" }}>TODO: fetch from GET /api/it/device-health</p>
    </div>
  );
}
