// Finance Panel - sees asset/cost data only, zero employee location data
// of any kind (Section 7).
import { useAssetInventory } from "../hooks/useAssetInventory";
import styles from "./OpsPanel.module.css";

function formatCurrency(value) {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" }).format(value);
}

function statusClass(status) {
  if (status === "active") return "ok";
  if (status === "in_repair") return "warn";
  if (status === "retired") return "offline";
  return "";
}

export default function FinancePanel() {
  const { assets, loading, error } = useAssetInventory();

  const totalValue = assets.reduce((sum, a) => sum + (a.purchase_cost ?? 0), 0);
  const needingReplacement = assets.filter((a) => {
    if (!a.replacement_due_date) return false;
    return new Date(a.replacement_due_date) < new Date();
  }).length;

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.title}>Finance panel</h1>
        <p className={styles.subtitle}>
          Hardware asset inventory, cost tracking, tag replacement/procurement records.
        </p>
      </div>

      <div className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Total assets</div>
          <div className={styles.summaryValue}>{assets.length}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Total value</div>
          <div className={styles.summaryValue}>{formatCurrency(totalValue)}</div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Past replacement date</div>
          <div className={`${styles.summaryValue} ${needingReplacement > 0 ? styles.warn : styles.ok}`}>
            {needingReplacement}
          </div>
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load asset inventory: {error}
        </div>
      )}

      {loading && assets.length === 0 && !error && (
        <div className={styles.emptyState}>Loading asset inventory…</div>
      )}

      {!loading && assets.length === 0 && !error && (
        <div className={styles.emptyState}>No assets on record.</div>
      )}

      {assets.length > 0 && (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Status</th>
              <th>Asset</th>
              <th>Type</th>
              <th style={{ textAlign: "right" }}>Cost</th>
              <th>Purchased</th>
              <th>Replacement due</th>
            </tr>
          </thead>
          <tbody>
            {assets.map((a) => (
              <tr key={a.asset_id}>
                <td>
                  <span className={`${styles.statusDot} ${styles[statusClass(a.status)] ?? ""}`} />
                  {a.status}
                </td>
                <td className={styles.mono}>{a.asset_id}</td>
                <td>{a.asset_type}</td>
                <td className={styles.mono} style={{ textAlign: "right" }}>
                  {formatCurrency(a.purchase_cost)}
                </td>
                <td className={styles.mono}>
                  {a.purchase_date ? new Date(a.purchase_date).toLocaleDateString() : "—"}
                </td>
                <td className={styles.mono}>
                  {a.replacement_due_date ? new Date(a.replacement_due_date).toLocaleDateString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
