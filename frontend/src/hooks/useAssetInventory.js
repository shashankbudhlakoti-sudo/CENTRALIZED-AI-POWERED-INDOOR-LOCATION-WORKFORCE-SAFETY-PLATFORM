// Polls a PROPOSED GET /finance/assets endpoint - not yet confirmed with
// Shashank. Path adapted from the scaffold's original TODO comment
// (GET /api/finance/assets) to match the real /api/v1 prefix.
//
// Zero employee location data of any kind (Section 7) - this is hardware
// asset/cost data only (tag inventory, procurement, replacement records).
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "../auth/apiClient";

const POLL_INTERVAL_MS = 30000; // asset data changes slowly - no need to poll as often

export function useAssetInventory() {
  const [assets, setAssets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchOnce() {
      try {
        const data = await apiFetch("/finance/assets");
        if (!cancelled) {
          setAssets(data);
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

  return { assets, loading, error };
}
