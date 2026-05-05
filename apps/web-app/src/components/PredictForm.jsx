// @ts-check
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { ApiError, predictCoverage } from "../api/client.js";
import { PredictionView } from "./PredictionView.jsx";

const PRESETS = [
  { label: "Đà Nẵng (gần GW)", lat: 16.115, lng: 108.278 },
  { label: "TP.HCM (gần GW)", lat: 10.7717, lng: 106.7042 },
  { label: "Hà Nội (gần GW)", lat: 21.0303, lng: 105.8125 },
  { label: "Cà Mau (xa GW)", lat: 9.179, lng: 105.15 },
];

export function PredictForm() {
  const [lat, setLat] = useState("16.0544");
  const [lng, setLng] = useState("108.2022");
  const [sf, setSf] = useState(7);

  const m = useMutation({
    mutationFn: predictCoverage,
  });

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    m.mutate({
      latitude: Number(lat),
      longitude: Number(lng),
      spreading_factor: sf,
      frequency_mhz: 868,
    });
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="grid gap-4 sm:grid-cols-4">
        <label className="block">
          <span className="block text-sm font-medium text-slate-700">
            Vĩ độ (°)
          </span>
          <input
            type="number"
            step="0.0001"
            value={lat}
            onChange={(e) => setLat(e.target.value)}
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
            required
          />
        </label>
        <label className="block">
          <span className="block text-sm font-medium text-slate-700">
            Kinh độ (°)
          </span>
          <input
            type="number"
            step="0.0001"
            value={lng}
            onChange={(e) => setLng(e.target.value)}
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
            required
          />
        </label>
        <label className="block">
          <span className="block text-sm font-medium text-slate-700">
            Spreading Factor
          </span>
          <select
            value={sf}
            onChange={(e) => setSf(Number(e.target.value))}
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
          >
            {[7, 8, 9, 10, 11, 12].map((v) => (
              <option key={v} value={v}>
                SF{v}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={m.isPending}
          className="self-end rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
        >
          {m.isPending ? "Đang dự đoán…" : "Dự đoán"}
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => {
              setLat(String(p.lat));
              setLng(String(p.lng));
            }}
            className="rounded-full border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-100"
          >
            {p.label}
          </button>
        ))}
      </div>

      {m.isError && m.error instanceof ApiError && (
        <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-800">
          <div className="font-semibold">{m.error.problem.title}</div>
          {m.error.problem.detail && (
            <div className="mt-1 text-red-700">{m.error.problem.detail}</div>
          )}
          {m.error.problem.code && (
            <div className="mt-1 text-xs text-red-600">
              code: {m.error.problem.code}
            </div>
          )}
        </div>
      )}

      {m.isSuccess && <PredictionView prediction={m.data} />}
    </div>
  );
}
