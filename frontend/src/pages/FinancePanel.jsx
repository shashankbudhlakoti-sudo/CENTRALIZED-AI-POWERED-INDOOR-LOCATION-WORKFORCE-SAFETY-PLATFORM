// Finance Panel - sees asset counts only, zero employee location data of
// any kind (Section 7).
//
// Real endpoint (GET /finance/assets, verified against main.py) returns
// exactly three numbers: total_assets, assigned, unassigned. No per-asset
// cost/purchase-date/type data exists - the earlier asset-ledger-table
// assumption doesn't match what the backend actually returns.
import { useAssetInventory } from "../hooks/useAssetInventory";
import styles from "./OpsPanel.module.css";

export default function FinancePanel() {
  const { summary, loading, error } = useAssetInventory();
  const { total_assets, assigned, unassigned } = summary;
  const assignedPct = total_assets > 0 ? Math.round((assigned / total_assets) * 100) : 0;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Finance panel</h1>
        <p className={styles.subtitle}>
          Hardware asset inventory, cost tracking, tag replacement/procurement records.
        </p>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load asset inventory: {error}
        </div>
      )}

      {loading && !error && (
        <div className={styles.emptyState}>Loading asset inventory…</div>
      )}

      {!loading && !error && total_assets === 0 && (
        <div className={styles.emptyState}>No assets on record.</div>
      )}

      {!loading && !error && total_assets > 0 && (
        <>
          <div className={styles.summaryRow}>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Total assets</div>
              <div className={styles.summaryValue}>{total_assets}</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Assigned</div>
              <div className={`${styles.summaryValue} ${styles.ok}`}>{assigned}</div>
            </div>
            <div className={styles.summaryCard}>
              <div className={styles.summaryLabel}>Unassigned</div>
              <div className={styles.summaryValue}>{unassigned}</div>
            </div>
          </div>

          <div className={styles.summaryLabel} style={{ marginBottom: 8 }}>
            Assignment rate: {assignedPct}%
          </div>
          <div className={styles.shiftBar} style={{ width: "100%" }}>
            <div
              className={styles.shiftBarSegment}
              style={{ width: `${assignedPct}%`, background: "#3DDC84" }}
              title={`Assigned: ${assigned}`}
            />
            <div
              className={styles.shiftBarSegment}
              style={{ width: `${100 - assignedPct}%`, background: "#5A6B87" }}
              title={`Unassigned: ${unassigned}`}
            />
          </div>
        </>
      )}
    </div>
  );
}
