// Live alert feed for the Security panel. Shows active (unacknowledged)
// alerts from zone_breach/inactivity/tag_offline/checkpoint_mismatch
// detection, with a one-click acknowledge action - this is the UI for
// anomaly detection logic that already exists and previously had nothing
// displaying it.
import { useState } from "react";
import { useAlertFeed } from "../hooks/useAlertFeed";
import styles from "./AlertFeed.module.css";

const TYPE_LABELS = {
  zone_breach: "Zone breach",
  fall_detected: "Fall detected",
  inactivity: "Inactivity",
  panic_button: "Panic button",
  unauthorized_access: "Unauthorized access",
  checkpoint_mismatch: "Checkpoint mismatch",
  tag_offline: "Tag offline",
};

function SeverityDot({ severity }) {
  return <span className={`${styles.dot} ${styles[`dot-${severity}`]}`} aria-hidden="true" />;
}

function formatTimestamp(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diffSec = Math.round((now - d) / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function AlertRow({ alert, onAcknowledge }) {
  const [acking, setAcking] = useState(false);

  async function handleAck() {
    setAcking(true);
    await onAcknowledge(alert.id);
    // No need to reset acking - row disappears once the parent's list
    // updates (optimistic removal in the hook).
  }

  return (
    <li className={styles.row}>
      <SeverityDot severity={alert.severity} />
      <div className={styles.rowBody}>
        <div className={styles.rowTop}>
          <span className={styles.typeLabel}>{TYPE_LABELS[alert.alert_type] ?? alert.alert_type}</span>
          <span className={styles.timestamp}>{formatTimestamp(alert.created_at)}</span>
        </div>
        {alert.details && (
          <div className={styles.details}>
            {alert.zone_name ?? alert.zone_id ? `Zone: ${alert.zone_name ?? alert.zone_id}` : null}
            {alert.employee_name ?? alert.employee_id ? ` · ${alert.employee_name ?? alert.employee_id}` : null}
          </div>
        )}
      </div>
      <button
        className={styles.ackButton}
        onClick={handleAck}
        disabled={acking}
      >
        {acking ? "…" : "Acknowledge"}
      </button>
    </li>
  );
}

export default function AlertFeed() {
  const { alerts, loading, error, acknowledge } = useAlertFeed();

  const critical = alerts.filter((a) => a.severity === "critical").length;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2 className={styles.title}>Active alerts</h2>
        <div className={styles.summary}>
          {critical > 0 && <span className={styles.criticalBadge}>{critical} critical</span>}
          <span className={styles.count}>{alerts.length} active</span>
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {loading && alerts.length === 0 && !error && (
        <div className={styles.emptyState}>Loading alerts…</div>
      )}

      {!loading && alerts.length === 0 && !error && (
        <div className={styles.emptyState}>No active alerts. All clear.</div>
      )}

      <ul className={styles.list}>
        {alerts.map((alert) => (
          <AlertRow key={alert.id} alert={alert} onAcknowledge={acknowledge} />
        ))}
      </ul>
    </div>
  );
}
