/**
 * LiveMap
 *
 * Indoor floor-plan view with live badge positions. Uses Leaflet's
 * CRS.Simple so coordinates are plain x/y (meters or pixels on the floor
 * plan image) instead of lat/lng — this is an indoor map, not a
 * geographic one.
 *
 * Requires (not yet in this repo's package.json — add them):
 *   npm install leaflet react-leaflet
 *
 * Swap FLOORPLAN_URL / FLOORPLAN_BOUNDS for your real floor plan asset
 * and its pixel dimensions once you have one.
 */
import { useMemo } from "react";
import { MapContainer, ImageOverlay, Polygon, Marker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { usePositionFeed } from "../hooks/usePositionFeed";
import styles from "./LiveMap.module.css";

const FLOORPLAN_URL = "/floorplan-placeholder.svg";
const FLOORPLAN_BOUNDS = [
  [0, 0],
  [700, 1000],
]; // [y, x] max — matches the placeholder SVG's 1000x700 canvas

const STALE_AFTER_MS = 10_000; // badge dot starts fading past this age
const OFFLINE_AFTER_MS = 30_000; // badge dot goes grey/dashed past this age

function freshnessClass(updatedAt) {
  const ageMs = Date.now() - new Date(updatedAt).getTime();
  if (ageMs > OFFLINE_AFTER_MS) return styles.badgeOffline;
  if (ageMs > STALE_AFTER_MS) return styles.badgeStale;
  return styles.badgeLive;
}

function badgeIcon(updatedAt) {
  const cls = freshnessClass(updatedAt);
  return L.divIcon({
    className: "",
    html: `<span class="${styles.badgeDot} ${cls}"><span class="${styles.badgeRing}"></span></span>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function ConnectionBadge({ state }) {
  const label = {
    connecting: "Connecting…",
    live: "Live",
    polling: "Reconnecting (polling)",
    offline: "Offline",
  }[state];

  return (
    <div className={`${styles.statusPill} ${styles["status_" + state]}`}>
      <span className={styles.statusDot} />
      {label}
    </div>
  );
}

function Legend() {
  return (
    <div className={styles.legend}>
      <div className={styles.legendTitle}>Position freshness</div>
      <div className={styles.legendRow}><span className={`${styles.legendDot} ${styles.badgeLive}`} /> Live (&lt;10s)</div>
      <div className={styles.legendRow}><span className={`${styles.legendDot} ${styles.badgeStale}`} /> Stale (10–30s)</div>
      <div className={styles.legendRow}><span className={`${styles.legendDot} ${styles.badgeOffline}`} /> Lost (&gt;30s)</div>
    </div>
  );
}

/** Optional zone overlays — pass real zone polygons from /api/zones once available. */
function ZoneOverlays({ zones }) {
  return zones.map((zone) => (
    <Polygon
      key={zone.zone_id}
      positions={zone.points}
      pathOptions={{
        color: zone.restricted ? "#F0455C" : "#2A3A55",
        weight: 1.5,
        dashArray: "6 4",
        fillColor: zone.restricted ? "#F0455C" : "#3A4D6E",
        fillOpacity: zone.restricted ? 0.08 : 0.04,
      }}
    >
      <Tooltip sticky>{zone.name}</Tooltip>
    </Polygon>
  ));
}

export default function LiveMap({
  wsUrl = "ws://localhost:8000/ws/positions",
  restUrl = "http://localhost:8000/api/positions",
  authToken,
  zones = [],
}) {
  const { positions, connectionState } = usePositionFeed({ wsUrl, restUrl, authToken });
  const badgeList = useMemo(() => Object.values(positions), [positions]);

  return (
    <div className={styles.wrapper}>
      <MapContainer
        crs={L.CRS.Simple}
        bounds={FLOORPLAN_BOUNDS}
        maxBoundsViscosity={1.0}
        zoomSnap={0.25}
        className={styles.map}
      >
        <ImageOverlay url={FLOORPLAN_URL} bounds={FLOORPLAN_BOUNDS} />
        <ZoneOverlays zones={zones} />
        {badgeList.map((badge) => (
          <Marker
            key={badge.badge_id}
            position={[badge.y, badge.x]}
            icon={badgeIcon(badge.updated_at)}
          >
            <Tooltip direction="top" offset={[0, -10]}>
              <div className={styles.tooltipBody}>
                <div className={styles.tooltipId}>{badge.badge_id}</div>
                <div className={styles.tooltipMeta}>{badge.zone_id}</div>
                {badge.confidence != null && (
                  <div className={styles.tooltipMeta}>conf {badge.confidence.toFixed(2)}</div>
                )}
              </div>
            </Tooltip>
          </Marker>
        ))}
      </MapContainer>

      <div className={styles.overlayTopLeft}>
        <ConnectionBadge state={connectionState} />
        <Legend />
      </div>

      <div className={styles.overlayTopRight}>
        <div className={styles.badgeCount}>{badgeList.length} tracked</div>
      </div>
    </div>
  );
}
