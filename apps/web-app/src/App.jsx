// @ts-check
import { useState } from "react";
import { AdminGateways } from "./components/AdminGateways.jsx";
import { BulkLookup } from "./components/BulkLookup.jsx";
import { CoverageMap } from "./components/CoverageMap.jsx";
import { strings } from "./strings.js";

/** @typedef {"predict" | "map" | "heatmap" | "bulk" | "admin"} Tab */

export function App() {
  const [tab, setTab] = useState(/** @type {Tab} */ ("map"));
  const t = strings.app;

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <div>
            <h1 className="text-lg font-bold text-slate-900">{t.title}</h1>
    
          </div>
          <nav className="flex gap-2">
            <TabButton active={tab === "map"} onClick={() => setTab("map")}>
              {t.tabs.map}
            </TabButton>
            <TabButton active={tab === "heatmap"} onClick={() => setTab("heatmap")}>
              {t.tabs.heatmap}
            </TabButton>

            <TabButton active={tab === "predict"} onClick={() => setTab("predict")}>
              {t.tabs.predict}
            </TabButton>
            <TabButton active={tab === "bulk"} onClick={() => setTab("bulk")}>
              {t.tabs.bulk}
            </TabButton>
            <TabButton active={tab === "admin"} onClick={() => setTab("admin")}>
              {t.tabs.admin}
            </TabButton>
            
          </nav>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {tab === "map" && <CoverageMap mode="points" />}
        {tab === "heatmap" && <CoverageMap mode="heatmap" />}
        {tab === "predict" && <CoverageMap mode="predict" />}
        {tab === "bulk" && (
          <div className="h-full overflow-y-auto">
            <BulkLookup />
          </div>
        )}
        {tab === "admin" && (
          <div className="h-full overflow-y-auto">
            <AdminGateways />
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
