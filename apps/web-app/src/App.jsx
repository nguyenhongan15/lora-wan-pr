// @ts-check
import { useState } from "react";
import { CoverageMap } from "./components/CoverageMap.jsx";
import { PredictForm } from "./components/PredictForm.jsx";

/** @typedef {"predict" | "map"} Tab */

export function App() {
  const [tab, setTab] = useState(/** @type {Tab} */ ("map"));
  const isMap = tab === "map";

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <div>
            <h1 className="text-lg font-bold text-slate-900">
              LoRa Coverage Vietnam
            </h1>
            <p className="text-xs text-slate-500">
              v2 — Đà Nẵng pilot. Stage 1 + 200 survey points.
            </p>
          </div>
          <nav className="flex gap-2">
            <TabButton active={isMap} onClick={() => setTab("map")}>
              Bản đồ phủ sóng
            </TabButton>
            <TabButton active={!isMap} onClick={() => setTab("predict")}>
              Dự đoán điểm
            </TabButton>
          </nav>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {isMap ? (
          <CoverageMap />
        ) : (
          <div className="mx-auto h-full max-w-6xl overflow-y-auto px-6 py-8">
            <PredictForm />
          </div>
        )}
      </main>
    </div>
  );
}

/**
 * @param {{ active: boolean, onClick: () => void, children: import("react").ReactNode }} props
 */
function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-md px-3 py-1.5 text-sm font-medium transition " +
        (active
          ? "bg-slate-900 text-white"
          : "border border-slate-300 text-slate-700 hover:bg-slate-100")
      }
    >
      {children}
    </button>
  );
}
