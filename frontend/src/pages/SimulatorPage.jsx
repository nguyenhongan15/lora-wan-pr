/**
 * SimulatorPage.jsx — 2 tabs:
 *   1. "Click giả định"   — click bản đồ thêm gateway giả định, mô phỏng phủ sóng (cũ)
 *   2. "Tối ưu candidates" — chọn từ candidates DB qua MCLP/LSCP greedy
 *
 * State 2 tab tách biệt, không ảnh hưởng nhau.
 * Map click chỉ hoạt động ở tab simulate.
 */

import { useState, useCallback, useEffect, useMemo } from "react";
import Map, { NavigationControl } from "react-map-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import S from "../strings";
import { api } from "../api";
import { isStandard, getConfig } from "../styles/mapbox";

import SimulatorPanel, { SimulatorLayer } from "../components/SimulatorPanel";
import AoiLayer              from "../components/AoiLayer";
import CandidateLayer, { CANDIDATE_LAYER_ID } from "../components/CandidateLayer";
import SelectedGatewayLayer  from "../components/SelectedGatewayLayer";
import OptimizerSidebar      from "../components/OptimizerSidebar";
import NavBar                from "../components/NavBar";

const TOKEN        = import.meta.env.VITE_MAPBOX_TOKEN;
const DA_NANG      = { longitude: 108.2022, latitude: 16.0544, zoom: 11 };
const MAP_STYLE    = "mapbox://styles/mapbox/standard";
const LIGHT_PRESET = "day";

const FULL_SLUG  = "danang";
const URBAN_SLUG = "danang_urban";

// Snapshot tx → so sánh stale (chỉ lat/lng).
function txKey(transmitters) {
  return JSON.stringify(transmitters.map(t => [t.lat, t.lng]));
}

export default function SimulatorPage() {
  const [tab, setTab] = useState("simulate");   // "simulate" | "optimize"

  // ─── Simulate tab state (giữ nguyên cũ) ────────────────────
  const [transmitters, setTransmitters] = useState([]);
  const [env,          setEnv]          = useState("urban");
  const [resolution,   setResolution]   = useState(50);
  const [txPower,      setTxPower]      = useState(14);
  const [txGain,       setTxGain]       = useState(8);
  const [txHeight,     setTxHeight]     = useState(30);
  const [useCalibration,  setUseCalibration]  = useState(false);
  const [simRunning,   setSimRunning]   = useState(false);
  const [simResult,    setSimResult]    = useState(null);
  const [simParams,    setSimParams]    = useState(null);

  const isStale = useMemo(() => {
    if (!simParams) return false;
    return (
      simParams.env             !== env         ||
      simParams.resolution      !== resolution  ||
      simParams.txPower         !== txPower     ||
      simParams.txGain          !== txGain      ||
      simParams.txHeight        !== txHeight    ||
      simParams.useCalibration  !== useCalibration ||
      simParams.transmittersKey !== txKey(transmitters)
    );
  }, [simParams, env, resolution, txPower, txGain, txHeight, useCalibration, transmitters]);

  // ─── Optimize tab state ────────────────────────────────────
  const [aoiFull,   setAoiFull]   = useState(null);
  const [aoiUrban,  setAoiUrban]  = useState(null);
  const [candidates,setCandidates]= useState([]);
  const [showAoi,        setShowAoi]        = useState(true);
  const [showUrban,      setShowUrban]      = useState(true);
  const [showCandidates, setShowCandidates] = useState(true);

  const [optMode,        setOptMode]        = useState("mclp");
  const [optKMax,        setOptKMax]        = useState(10);
  const [optTarget,      setOptTarget]      = useState(0.7);
  const [optSf,          setOptSf]          = useState(12);
  const [optTxPower,     setOptTxPower]     = useState(14);
  const [optTxHeight,    setOptTxHeight]    = useState(30);
  const [optCostAware,   setOptCostAware]   = useState(true);
  const [optRunning,     setOptRunning]     = useState(false);
  const [optResult,      setOptResult]      = useState(null);
  const [history,        setHistory]        = useState([]);

  const [toast, setToast] = useState(null);

  // ─── Lazy load AOI + candidates + history khi switch sang optimize ──
  useEffect(() => {
    if (tab !== "optimize") return;

    if (!aoiFull) {
      api.getAoi(FULL_SLUG).then(setAoiFull).catch(e => console.warn("[aoi]", e.message));
    }
    if (!aoiUrban) {
      api.getAoi(URBAN_SLUG).then(setAoiUrban).catch(() => {});
    }
    if (candidates.length === 0) {
      api.getAoiCandidates(FULL_SLUG)
        .then(setCandidates)
        .catch(e => console.warn("[candidates]", e.message));
    }
    refreshHistory();
  }, [tab]);  // eslint-disable-line react-hooks/exhaustive-deps

  const refreshHistory = useCallback(() => {
    api.listOptimizationRuns(FULL_SLUG, { limit: 20 })
      .then(arr => setHistory(Array.isArray(arr) ? arr : []))
      .catch(e => console.warn("[history]", e.message));
  }, []);

  // ─── Simulate handlers (cũ) ────────────────────────────────
  const handleSimRun = useCallback(async () => {
    if (transmitters.length === 0) return;
    setSimRunning(true);
    setToast(S.app.toastSimulating);
    try {
      const tx = transmitters.map(t => ({
        lat: t.lat, lng: t.lng,
        txPowerDbm: txPower, antennaGainDbi: txGain, antennaHeightM: txHeight,
      }));
      const r = await api.simulateCoverage(tx, null, resolution, env, 923.0, {
        useCalibration,
      });
      setSimResult(r);
      setSimParams({
        env, resolution, txPower, txGain, txHeight, useCalibration,
        transmittersKey: txKey(transmitters),
      });
      setToast(null);
    } catch (e) {
      setToast(S.app.toastError(e.message));
      setTimeout(() => setToast(null), 4000);
    } finally {
      setSimRunning(false);
    }
  }, [transmitters, resolution, txPower, txGain, txHeight, env, useCalibration]);

  const handleSimClear = useCallback(() => {
    setTransmitters([]);
    setSimResult(null);
    setSimParams(null);
  }, []);

  // ─── Optimize handlers ─────────────────────────────────────
  const handleOptRun = useCallback(async () => {
    setOptRunning(true);
    setToast(S.app.toastOptimizing);
    try {
      const payload = {
        aoiSlug:        FULL_SLUG,
        urbanSlug:      URBAN_SLUG,
        mode:           optMode,
        kMax:           optMode === "mclp" ? optKMax : null,
        targetCoverage: optMode === "lscp" ? optTarget : null,
        kSafetyMax:     100,
        costAware:      optCostAware,
        coverageConfig: {
          model:             "hata",
          frequencyMhz:      923.0,
          sf:                optSf,
          txPowerDbm:        optTxPower,
          txAntennaHeightM:  optTxHeight,
          rxAntennaHeightM:  1.5,
          txAntennaGainDbi:  3.0,
          rxAntennaGainDbi:  2.0,
        },
        notes: `UI ${optMode} ${optMode === "mclp" ? `K=${optKMax}` : `target=${optTarget}`}`,
      };
      const result = await api.createOptimizationRun(payload);
      setOptResult(result);
      setToast(S.optimizer.toastSuccess(result.nSelected, result.coverageRatio));
      refreshHistory();
    } catch (e) {
      setToast(S.app.toastError(e.message));
    } finally {
      setOptRunning(false);
      setTimeout(() => setToast(null), 4000);
    }
  }, [optMode, optKMax, optTarget, optSf, optTxPower, optTxHeight, optCostAware, refreshHistory]);

  const handleSelectRun = useCallback(async (runId) => {
    try {
      const detail = await api.getOptimizationRun(runId);
      setOptResult(detail);
    } catch (e) {
      setToast(S.app.toastError(e.message));
      setTimeout(() => setToast(null), 4000);
    }
  }, []);

  const handleDeleteRun = useCallback(async (runId) => {
    try {
      await api.deleteOptimizationRun(runId);
      setHistory(arr => arr.filter(r => r.id !== runId));
      if (optResult?.id === runId) setOptResult(null);
    } catch (e) {
      setToast(S.app.toastError(e.message));
      setTimeout(() => setToast(null), 4000);
    }
  }, [optResult]);

  // ─── Map click — chỉ hoạt động ở simulate tab ──────────────
  const handleMapClick = useCallback((e) => {
    if (tab !== "simulate") return;
    setTransmitters(arr => [...arr, { lat: e.lngLat.lat, lng: e.lngLat.lng }]);
  }, [tab]);

  const std = isStandard(MAP_STYLE);
  const interactiveLayers = (tab === "optimize" && showCandidates) ? [CANDIDATE_LAYER_ID] : [];
  const mapCursor = tab === "simulate" ? "crosshair" : "default";

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", background: "#0f0f1a" }}>
      <NavBar />

      <Map
        id="main"
        mapboxAccessToken={TOKEN}
        initialViewState={{ ...DA_NANG, pitch: std ? 45 : 0, bearing: 0 }}
        mapStyle={MAP_STYLE}
        config={std ? getConfig(LIGHT_PRESET) : undefined}
        style={{ width: "100%", height: "100%", cursor: mapCursor }}
        interactiveLayerIds={interactiveLayers}
        onClick={handleMapClick}
      >
        <NavigationControl position="bottom-right" visualizePitch />

        {/* Simulate layers */}
        {tab === "simulate" && (
          <SimulatorLayer
            transmitters={transmitters}
            simResult={simResult}
            isStale={isStale}
          />
        )}

        {/* Optimize layers */}
        {tab === "optimize" && (
          <>
            <AoiLayer
              fullAoi={showAoi   ? aoiFull  : null}
              urbanAoi={showUrban ? aoiUrban : null}
            />
            {showCandidates && <CandidateLayer candidates={candidates} />}
            <SelectedGatewayLayer selections={optResult?.selectionDetails ?? []} />
          </>
        )}
      </Map>

      {/* Sidebar: tab toggle + active panel */}
      <div style={sidebarStyle}>
        {/* Tab toggle */}
        <div style={tabsWrapStyle}>
          <button onClick={() => setTab("simulate")} style={tabStyle(tab === "simulate")}>
            {S.optimizer.tabSimulate}
          </button>
          <button onClick={() => setTab("optimize")} style={tabStyle(tab === "optimize")}>
            {S.optimizer.tabOptimize}
          </button>
        </div>

        {tab === "simulate" ? (
          <SimulatorPanel
            transmitters={transmitters}    onClear={handleSimClear}
            environment={env}              onEnv={setEnv}
            resolution={resolution}        onResolution={setResolution}
            txPower={txPower}              onTxPower={setTxPower}
            txGain={txGain}                onTxGain={setTxGain}
            txHeight={txHeight}            onTxHeight={setTxHeight}
            useCalibration={useCalibration} onUseCalibration={setUseCalibration}
            running={simRunning}           onRun={handleSimRun}
            isStale={isStale}
          />
        ) : (
          <OptimizerSidebar
            showAoi={showAoi}                 onToggleAoi={setShowAoi}
            showUrban={showUrban}             onToggleUrban={setShowUrban}
            showCandidates={showCandidates}   onToggleCandidates={setShowCandidates}
            mode={optMode}                    onMode={setOptMode}
            kMax={optKMax}                    onKMax={setOptKMax}
            targetCoverage={optTarget}        onTargetCoverage={setOptTarget}
            sf={optSf}                        onSf={setOptSf}
            txPowerDbm={optTxPower}           onTxPowerDbm={setOptTxPower}
            txAntennaHeightM={optTxHeight}    onTxAntennaHeightM={setOptTxHeight}
            costAware={optCostAware}          onCostAware={setOptCostAware}
            running={optRunning}              onRun={handleOptRun}
            result={optResult}
            history={history}
            onSelectRun={handleSelectRun}
            onDeleteRun={handleDeleteRun}
          />
        )}
      </div>

      {toast && (
        <div style={toastStyle}>
          {toast}
        </div>
      )}
    </div>
  );
}


// ── Styles ───────────────────────────────────────────────────

const sidebarStyle = {
  position: "absolute", top: 12, left: 12, zIndex: 1000,
  width: 280,
  maxHeight: "calc(100vh - 24px)", overflowY: "auto",
  display: "flex", flexDirection: "column", gap: 8,
};

const tabsWrapStyle = {
  display: "flex", gap: 4, padding: 4,
  background: "rgba(20,20,30,0.88)", backdropFilter: "blur(8px)",
  borderRadius: 10,
  border: "1px solid rgba(255,255,255,0.1)",
};

const tabStyle = (active) => ({
  flex: 1, padding: "8px 10px", borderRadius: 7, border: "none",
  cursor: "pointer", fontSize: 12, fontWeight: 600,
  background: active ? "#7c3aed" : "transparent",
  color: active ? "#fff" : "#cbd5e1",
  transition: "all .15s",
});

const toastStyle = {
  position: "absolute", bottom: 24, left: "50%", transform: "translateX(-50%)",
  background: "rgba(20,20,30,0.95)", color: "#f9fafb",
  padding: "10px 20px", borderRadius: 10, fontSize: 13,
  border: "1px solid rgba(255,255,255,0.15)", zIndex: 2000,
  backdropFilter: "blur(8px)", maxWidth: "80vw", textAlign: "center",
};