import React, { useState } from "react";
import styles from "./OpsPanel.module.css"; 

export default function OpsPanel() {
  // Real-world dynamic states initialized to empty/loading structures
  const [activeAssets, setActiveAssets] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  return (
    <div className={styles.page}>
      {/* Header Block */}
      <header className={styles.header}>
        <h1 className={styles.title}>?? Airport Operations Control Center</h1>
        <p className={styles.subtitle}>Real-time indoor asset positioning and safety tracking</p>
      </header>

      {/* Error State Banner */}
      {error && <div className={styles.errorBanner}>{error}</div>}

      {/* Operations Quick Summary Row */}
      <section className={styles.summaryRow}>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Active Tracked Badges</div>
          <div className={`${styles.summaryValue} ${styles.ok}`}>
            {isLoading ? "..." : activeAssets.length}
          </div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Zone Load Status</div>
          <div className={`${styles.summaryValue} ${activeAssets.length > 0 ? styles.ok : styles.warn}`}>
            {isLoading ? "..." : activeAssets.length > 0 ? "Active" : "No Data"}
          </div>
        </div>
        <div className={styles.summaryCard}>
          <div className={styles.summaryLabel}>Active Incidents</div>
          <div className={`${styles.summaryValue} ${incidents.length > 0 ? styles.critical : styles.ok}`}>
            {isLoading ? "..." : String(incidents.length).padStart(2, "0")}
          </div>
        </div>
      </section>

      {/* Main Split Layout Grid */}
      <main className={styles.opsGrid}>
        
        {/* Left Side: Live Asset / Zone Tracking Card */}
        <div className={styles.tableCard}>
          <h3 className={styles.feedTitle}>Critical Zone Overview</h3>
          
          {isLoading ? (
            <div className={styles.emptyState}>Loading live tracking telemetry...</div>
          ) : activeAssets.length === 0 ? (
            <div className={styles.emptyState}>No tracked assets currently active in terminal zones.</div>
          ) : (
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Zone Location</th>
                  <th>Asset Type</th>
                  <th>Status</th>
                  <th>Last Ping</th>
                </tr>
              </thead>
              <tbody>
                {activeAssets.map((asset, index) => (
                  <tr key={asset.id || index}>
                    <td>{asset.zoneName || asset.zoneId}</td>
                    <td>{asset.type}</td>
                    <td>
                      <span className={`${styles.statusDot} ${styles[asset.statusClass || "ok"]}`}></span>
                      {asset.statusText}
                    </td>
                    <td className={styles.mono}>{asset.lastPing}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Right Side: Live Incident Activity Feed */}
        <div className={styles.feedCard}>
          <h3 className={styles.feedTitle}>Live Incident Log</h3>
          
          {isLoading ? (
            <div className={styles.emptyState}>Syncing incident feeds...</div>
          ) : incidents.length === 0 ? (
            <div className={styles.emptyState}>No active security breaches or dwell tracking incidents reported.</div>
          ) : (
            <div className={styles.alertList}>
              {incidents.map((incident, index) => (
                <div 
                  key={incident.id || index} 
                  className={`${styles.alertItem} ${incident.severity === "warning" ? styles.warning : ""}`}
                >
                  <div>{incident.message}</div>
                  <div className={styles.alertMeta}>
                    <span>{incident.location}</span>
                    <span>{incident.timeAgo}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

      </main>
    </div>
  );
}
