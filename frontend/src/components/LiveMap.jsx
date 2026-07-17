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
import { useEffect, useMemo } from "react";
import { MapContainer, ImageOverlay, Polygon, Marker, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { usePositionFeed } from "../hooks/usePositionFeed";
import styles from "./LiveMap.module.css";

const FLOORPLAN_URL = "/floorplan-placeholder.svg";
const FLOORPLAN_BOUNDS = [
  [0, 0],
  [4.11, 4.45],
]; // [y, x] max in real meters — y = room length (4.11m), x = room width (4.45m), matching gateway.py's GATEWAY_POSITIONS coordinate system

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

/**
 * Ray-casting point-in-polygon test. Points and polygon vertices are both
 * [y, x] pairs (matching FLOORPLAN_BOUNDS / Leaflet CRS.Simple convention
 * used everywhere else in this file — NOT geographic lat/lng).
 */
function pointInPolygon([py, px], vertices) {
  let inside = false;
  for (let i = 0, j = vertices.length - 1; i < vertices.length; j = i++) {
    const [yi, xi] = vertices[i];
    const [yj, xj] = vertices[j];
    const intersects =
      yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi;
    if (intersects) inside = !inside;
  }
  return inside;
}

/**
 * Resolves which zone a badge is standing in by testing its position against
 * each zone polygon. The backend doesn't return zone_id on position events
 * (see usePositionFeed.js), so this fills that gap client-side using the
 * zone polygons already passed into LiveMap. If a badge's point falls inside
 * more than one polygon (overlapping zones), the first match wins — revisit
 * if zones start overlapping intentionally.
 */
function resolveZoneId(badge, zones) {
  if (badge.zone_id) return badge.zone_id; // respect it if the backend ever does send one
  const match = zones.find((zone) => pointInPolygon([badge.y, badge.x], zone.points));
  return match ? match.zone_id : null;
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

/**
 * Forces Leaflet to re-measure its container after mount and on window
 * resize. Needed because the container's height now comes from CSS
 * (80vh, see LiveMap.module.css) rather than a hardcoded pixel value —
 * Leaflet only measures once at mount and won't notice later layout
 * shifts (sidebar toggles, font loading reflow, etc.) on its own.
 */
function ResizeHandler() {
  const map = useMap();
  useEffect(() => {
    const handleResize = () => map.invalidateSize();
    window.addEventListener("resize", handleResize);
    const t = setTimeout(handleResize, 100); // catch late layout settling on mount
    return () => {
      window.removeEventListener("resize", handleResize);
      clearTimeout(t);
    };
  }, [map]);
  return null;
}

export default function LiveMap({
  wsUrl = "ws://localhost:8000/ws",
  restUrl = "http://localhost:8000/api/v1/positions/latest",
  authToken,
  zones = [],
}) {
  const { positions, connectionState } = usePositionFeed({ wsUrl, restUrl, authToken });
  const badgeList = useMemo(
    () => Object.values(positions).map((badge) => ({ ...badge, zone_id: resolveZoneId(badge, zones) })),
    [positions, zones]
  );

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
        <ResizeHandler />
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
