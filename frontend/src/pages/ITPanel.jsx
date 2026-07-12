// IT Panel - Section 7: sees device/system health only, never employee
// identity tied to positions (device IDs only).
//
// Real endpoint (GET /it/device-health, verified against main.py) returns
// summary counts + flat tag_id lists, NOT per-device rows with battery
// percentage/last-seen timestamps - there's no richer per-device detail
// available, so this renders ID chips rather than a detailed table.
import { useDeviceHealth } from "../hooks/useDeviceHealth";
import styles from "./OpsPanel.module.css";

export default function ITPanel() {
  const { summary, loading, error } = useDeviceHealth();
  const { total_tags, active_tags, low_battery, possibly_offline } = summary;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>IT panel</h1>
        <p className={styles.subtitle}>
          Beacon/gateway health, tag battery status, system uptime, network diagnostics.
        </p>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load device health: {error}
        </div>
      )}

      {loading && !error && (
        <div className={styles.emptyState}>Loading device health…</div>
      )}

      {!loading && !error && (
        <>
          <div className={styles.summaryRow}>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Total tags</div>
              <div className={styles.summaryValue}>{total_tags}</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Active tags</div>
              <div className={`${styles.summaryValue} ${styles.ok}`}>{active_tags}</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Low battery (&lt;20%)</div>
              <div className={`${styles.summaryValue} ${low_battery.length > 0 ? styles.critical : styles.ok}`}>
                {low_battery.length}
              </div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Possibly offline (&gt;1h silent)</div>
              <div className={`${styles.summaryValue} ${possibly_offline.length > 0 ? styles.warn : styles.ok}`}>
                {possibly_offline.length}
              </div>
            </div>
          </div>

          {total_tags === 0 ? (
            <div className={styles.emptyState}>No devices reporting yet.</div>
          ) : (
            <>
              {low_battery.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div className={styles.summaryLabel} style={{ marginBottom: 8 }}>Low battery tag IDs</div>
                  <div className={styles.mono} style={{ color: "#F0455C", wordBreak: "break-all" }}>
                    {low_battery.join(", ")}
                  </div>
                </div>
              )}
              {possibly_offline.length > 0 && (
                <div>
                  <div className={styles.summaryLabel} style={{ marginBottom: 8 }}>Possibly offline tag IDs</div>
                  <div className={styles.mono} style={{ color: "#F2A93B", wordBreak: "break-all" }}>
                    {possibly_offline.join(", ")}
                  </div>
                </div>
              )}
              {low_battery.length === 0 && possibly_offline.length === 0 && (
                <div className={styles.emptyState}>All tags healthy - no low battery or offline devices.</div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
