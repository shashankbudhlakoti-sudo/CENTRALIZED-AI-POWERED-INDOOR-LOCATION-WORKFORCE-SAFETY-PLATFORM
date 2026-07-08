// Checkpoint review queue for the Security panel. Shows every checkpoint
// event with its captured photo and face-match result, so a human can
// review mismatches - this is the UI for a backend/ML pipeline that
// already exists and previously had nothing displaying it.
import { useState } from "react";
import { useCheckpointFeed } from "../hooks/useCheckpointFeed";
import styles from "./CheckpointViewer.module.css";

const STATUS_LABELS = {
  pending: "Reviewing",
  match: "Match",
  mismatch: "Mismatch",
  no_face: "No face detected",
};

const STATUS_FILTERS = [
  { value: null, label: "All" },
  { value: "mismatch", label: "Mismatches" },
  { value: "pending", label: "Pending" },
  { value: "match", label: "Matches" },
];

function StatusBadge({ status }) {
  return (
    <span className={`${styles.badge} ${styles[`badge-${status}`]}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function formatConfidence(value) {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function formatTimestamp(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function CheckpointCard({ event, onSelect }) {
  return (
    <button className={styles.card} onClick={() => onSelect(event)}>
      <div className={styles.thumbWrap}>
        {event.photo_url ? (
          <img src={event.photo_url} alt="" className={styles.thumb} />
        ) : (
          <div className={styles.thumbPlaceholder}>No image</div>
        )}
      </div>
      <div className={styles.cardBody}>
        <div className={styles.cardTop}>
          <StatusBadge status={event.match_status} />
          <span className={styles.timestamp}>{formatTimestamp(event.triggered_at)}</span>
        </div>
        <div className={styles.cardMeta}>
          <span>{event.zone_name ?? "Unknown zone"}</span>
          <span className={styles.confidence}>{formatConfidence(event.match_confidence)}</span>
        </div>
      </div>
    </button>
  );
}

function CheckpointDetail({ event, onClose }) {
  if (!event) return null;
  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.detailPanel} onClick={(e) => e.stopPropagation()}>
        <button className={styles.closeButton} onClick={onClose} aria-label="Close">
          ×
        </button>
        {event.photo_url ? (
          <img src={event.photo_url} alt="" className={styles.detailImage} />
        ) : (
          <div className={styles.thumbPlaceholder}>No image captured</div>
        )}
        <div className={styles.detailInfo}>
          <StatusBadge status={event.match_status} />
          <dl className={styles.detailList}>
            <dt>Zone</dt>
            <dd>{event.zone_name ?? "Unknown"}</dd>
            <dt>Confidence</dt>
            <dd>{formatConfidence(event.match_confidence)}</dd>
            <dt>Triggered</dt>
            <dd>{formatTimestamp(event.triggered_at)}</dd>
            <dt>Matched employee</dt>
            <dd>{event.match_employee_name ?? (event.match_employee_id ? event.match_employee_id : "None")}</dd>
          </dl>
        </div>
      </div>
    </div>
  );
}

export default function CheckpointViewer() {
  const [statusFilter, setStatusFilter] = useState(null);
  const { checkpoints, loading, error } = useCheckpointFeed(statusFilter);
  const [selected, setSelected] = useState(null);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h2 className={styles.title}>Checkpoint review</h2>
        <div className={styles.filters}>
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.label}
              className={`${styles.filterButton} ${statusFilter === f.value ? styles.filterActive : ""}`}
              onClick={() => setStatusFilter(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          Couldn't load checkpoint events: {error}
        </div>
      )}

      {loading && checkpoints.length === 0 && !error && (
        <div className={styles.emptyState}>Loading checkpoint events…</div>
      )}

      {!loading && checkpoints.length === 0 && !error && (
        <div className={styles.emptyState}>No checkpoint events yet.</div>
      )}

      <div className={styles.grid}>
        {checkpoints.map((event) => (
          <CheckpointCard key={event.id} event={event} onSelect={setSelected} />
        ))}
      </div>

      <CheckpointDetail event={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
