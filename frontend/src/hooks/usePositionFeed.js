/**
 * usePositionFeed
 *
 * Subscribes to live badge positions. Prefers a WebSocket push feed
 * (per the shared /contracts API spec); if the socket can't connect or
 * drops, falls back to REST polling on an interval so the map never just
 * goes blank because of a flaky connection.
 *
 * Raw backend record shape (GET /api/v1/positions/latest, and each
 * websocket broadcast payload):
 *
 *   {
 *     "tag_id": "...",
 *     "employee_id": "...",
 *     "floor": 1,
 *     "x": 412.5,
 *     "y": 268.0,
 *     "accuracy_m": 0.87,
 *     "recorded_at": "2026-07-06T10:15:32Z"
 *   }
 *
 * normalizeBadge() below maps that onto the shape LiveMap expects
 * (badge_id/zone_id/x/y/confidence/updated_at). Both the websocket
 * handler and the REST poll fallback route through it, so the two
 * transports can't drift apart again.
 */
import { useEffect, useRef, useState, useCallback } from "react";

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 15000;
const POLL_INTERVAL_MS = 3000;

function normalizeBadge(raw) {
  return {
    badge_id: raw.tag_id,
    zone_id: raw.zone_id ?? null,       // not in current backend response — open question, see note below
    x: raw.x,
    y: raw.y,
    confidence: raw.accuracy_m,          // or leave separate if semantics differ
    updated_at: raw.recorded_at,
  };
}

export function usePositionFeed({ wsUrl, restUrl, authToken }) {
  const [positions, setPositions] = useState({});
  const [connectionState, setConnectionState] = useState("connecting"); // connecting | live | polling | offline
  const wsRef = useRef(null);
  const pollTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const stoppedRef = useRef(false);

  const applyUpdate = useCallback((update) => {
    const badge = normalizeBadge(update);
    setPositions((prev) => ({ ...prev, [badge.badge_id]: badge }));
  }, []);

  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return;
    setConnectionState("polling");

    const poll = async () => {
      try {
        const res = await fetch(restUrl, {
          headers: authToken ? { Authorization: `Bearer ${authToken}` } : {},
        });
        if (!res.ok) throw new Error(`REST poll failed: ${res.status}`);
        const data = await res.json();
        const list = Array.isArray(data) ? data : data.positions || [];
        setPositions((prev) => {
          const next = { ...prev };
          for (const item of list) {
            const badge = normalizeBadge(item);
            next[badge.badge_id] = badge;
          }
          return next;
        });
      } catch (err) {
        // Stay in "polling" state and keep trying; only WS failures drive
        // us to "offline" — REST failures just mean this tick was stale.
        console.warn("[usePositionFeed] poll error", err);
      }
    };

    poll();
    pollTimerRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, [restUrl, authToken]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const connectWs = useCallback(() => {
    if (stoppedRef.current) return;

    const url = authToken ? `${wsUrl}?token=${encodeURIComponent(authToken)}` : wsUrl;
    const socket = new WebSocket(url);
    wsRef.current = socket;

    socket.onopen = () => {
      reconnectAttemptRef.current = 0;
      setConnectionState("live");
      stopPolling();
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const updates = Array.isArray(msg) ? msg : [msg];
        updates.forEach(applyUpdate);
      } catch (err) {
        console.warn("[usePositionFeed] malformed ws message", err);
      }
    };

    socket.onerror = () => {
      // onclose will fire next; handle reconnect/fallback there.
    };

    socket.onclose = () => {
      if (stoppedRef.current) return;
      startPolling(); // don't leave the map blank while we retry the socket

      const attempt = reconnectAttemptRef.current + 1;
      reconnectAttemptRef.current = attempt;
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
      setTimeout(connectWs, delay);
    };
  }, [wsUrl, authToken, applyUpdate, startPolling, stopPolling]);

  useEffect(() => {
    stoppedRef.current = false;

    if (wsUrl) {
      connectWs();
    } else {
      startPolling();
    }

    return () => {
      stoppedRef.current = true;
      stopPolling();
      wsRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsUrl, restUrl]);

  return { positions, connectionState };
}