// @ts-check
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, lookupCoverageByAddress, predictCoverage } from "../api/client.js";
import { strings } from "../strings.js";

const t = strings.addressSearch;

/**
 * @typedef {{
 *   latitude: number,
 *   longitude: number,
 *   displayName: string,
 *   prediction: import("../api/client.js").PredictionT,
 * }} ResolvedPayload
 */

/**
 * @param {{
 *   onResolved: (r: ResolvedPayload) => void,
 *   spreadingFactor: number,
 *   frequencyMhz?: number,
 * }} props
 */
export function AddressSearchBox({
  onResolved,
  spreadingFactor,
  frequencyMhz = 923,
}) {
  const [address, setAddress] = useState("");
  const [gpsState, setGpsState] = useState(
    /** @type {"idle" | "pending" | "error"} */ ("idle"),
  );
  const [gpsError, setGpsError] = useState(/** @type {string | null} */ (null));

  const m = useMutation({
    mutationFn: lookupCoverageByAddress,
    onSuccess: (data) => {
      onResolved({
        latitude: data.address.latitude,
        longitude: data.address.longitude,
        displayName: data.address.display_name,
        prediction: data.prediction,
      });
    },
  });

  // GPS dùng predictCoverage trực tiếp (đã có lat/lng — bỏ qua geocoding).
  const gpsPredict = useMutation({
    /** @param {{ latitude: number, longitude: number }} c */
    mutationFn: async (c) =>
      predictCoverage({
        latitude: c.latitude,
        longitude: c.longitude,
        spreading_factor: spreadingFactor,
        frequency_mhz: frequencyMhz,
      }),
    onSuccess: (prediction, vars) => {
      onResolved({
        latitude: vars.latitude,
        longitude: vars.longitude,
        displayName: `📍 ${vars.latitude.toFixed(5)}, ${vars.longitude.toFixed(5)}`,
        prediction,
      });
      setGpsState("idle");
    },
    onError: () => setGpsState("idle"),
  });

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    const trimmed = address.trim();
    if (!trimmed) return;
    m.mutate({
      address: trimmed,
      spreading_factor: spreadingFactor,
      frequency_mhz: frequencyMhz,
    });
  }

  function onGpsClick() {
    if (!("geolocation" in navigator)) {
      setGpsState("error");
      setGpsError(t.gpsUnsupported);
      return;
    }
    setGpsState("pending");
    setGpsError(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        gpsPredict.mutate({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
        });
      },
      (err) => {
        setGpsState("error");
        // PERMISSION_DENIED=1, POSITION_UNAVAILABLE=2, TIMEOUT=3.
        if (err.code === 1) setGpsError(t.gpsDenied);
        else if (err.code === 3) setGpsError(t.gpsTimeout);
        else setGpsError(t.gpsUnavailable);
      },
      { enableHighAccuracy: true, timeout: 10_000, maximumAge: 60_000 },
    );
  }

  const submitDisabled = m.isPending || address.trim().length === 0;
  const gpsBusy = gpsState === "pending" || gpsPredict.isPending;

  return (
    <div className="w-72 rounded-md border border-slate-200 bg-white p-3 shadow-sm">
      <form onSubmit={onSubmit} className="flex gap-2">
        <input
          type="text"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          placeholder={t.placeholder}
          className="flex-1 rounded-md border border-slate-300 px-2 py-1 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
          aria-label={t.ariaLabel}
        />
        <button
          type="button"
          onClick={onGpsClick}
          disabled={gpsBusy}
          title={t.gpsTitle}
          aria-label={t.gpsAria}
          className="rounded-md border border-slate-300 px-2 py-1 text-sm hover:bg-slate-100 disabled:opacity-50"
        >
          {gpsBusy ? "…" : "📍"}
        </button>
        <button
          type="submit"
          disabled={submitDisabled}
          className="rounded-md bg-slate-900 px-3 py-1 text-xs font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
        >
          {m.isPending ? t.submitPending : t.submit}
        </button>
      </form>

      {gpsState === "pending" && (
        <div className="mt-2 text-xs text-slate-500">{t.gpsPending}</div>
      )}

      {(gpsState === "error" || gpsPredict.isError) && (
        <div className="mt-2 rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-800">
          {gpsError ?? t.networkError}
        </div>
      )}

      {m.isError && (
        <div className="mt-2 rounded-md border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-800">
          {m.error instanceof ApiError ? (
            <>
              <div className="font-semibold">{m.error.problem.title}</div>
              {m.error.problem.detail && (
                <div className="mt-0.5">{m.error.problem.detail}</div>
              )}
            </>
          ) : (
            <div>{t.networkError}</div>
          )}
        </div>
      )}
    </div>
  );
}
