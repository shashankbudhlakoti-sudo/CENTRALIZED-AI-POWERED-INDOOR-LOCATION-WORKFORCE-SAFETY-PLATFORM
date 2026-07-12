// Polls GET /finance/assets - CONFIRMED shape from main.py (real, verified):
// { total_assets, assigned, unassigned }
//
// Three summary numbers only - no per-asset cost/purchase-date/type data
// exists in the real endpoint (the earlier per-asset ledger assumption
// doesn't match reality). Zero employee/location data either way.
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 30000;

export function useAssetInventory() {
  const [summary, setSummary] = useState({ total_assets: 0, assigned: 0, unassigned: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const data = await apiFetch("/finance/assets");
        if (!cancelled) {
          setSummary(data);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchOnce();
    pollRef.current = setInterval(fetchOnce, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(pollRef.current);
    };
  }, []);

  return { summary, loading, error };
}
