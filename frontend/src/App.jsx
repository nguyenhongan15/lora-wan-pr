import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import Map, { NavigationControl } from "react-map-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import S from "./strings";

import { api, getCachedModelId, setCachedModelId } from "./api";
import { rssiToIntensity, loadRssiConfig, snrMargin, findNearestGateway } from "./utils";
import { isStandard, getConfig } from "./styles/mapbox";

import ScatterLayer, { SCATTER_LAYER_ID } from "./components/ScatterLayer";
import HeatmapLayer     from "./components/HeatmapLayer";
import MLGridLayer      from "./components/MLGridLayer";
import GatewayMarkers   from "./components/GatewayMarkers";
import StatsPanel       from "./components/StatsPanel";
import Toolbar          from "./components/Toolbar";
import UncertaintyLayer from "./components/UncertaintyLayer";
import NavBar           from "./components/NavBar";

const TOKEN            = import.meta.env.VITE_MAPBOX_TOKEN;
const DEFAULT_CAMPAIGN = "d0000000-0000-0000-0000-000000000001";
const DA_NANG          = { longitude: 108.2022, latitude: 16.0544, zoom: 14 };
const ML_ALGOS         = new Set(["xgboost", "random_forest", "gaussian_process"]);

function normalizeFeature(f) {
  if (!f || f.type !== "Feature") return f;
  const p = f.properties ?? {};
  return {
    ...f,
    properties: {
      ...p,
      rssiDbm:         p.rssiDbm         ?? null,
      snrDb:           p.snrDb           ?? null,
      spreadingFactor: p.spreadingFactor ?? null,
      gatewayId:       p.gatewayId       ?? null,
    },
  };
}

export default function App() {
  const [mode, setMode]                   = useState("scatter");
  const [campaignId, setCampaignId]       = useState(DEFAULT_CAMPAIGN);
  const [showGateways, setShowGateways]   = useState(true);
  const [showRangeCircles, setShowRangeCircles] = useState(true);
  const [rangeKm, setRangeKm]             = useState(2);
  const [mapStyle, setMapStyle]           = useState("mapbox://styles/mapbox/standard");
  const [lightPreset, setLightPreset]     = useState("day");
  const std                               = isStandard(mapStyle);
  const mapRef                            = useRef(null);

  const [campaigns, setCampaigns]   = useState([]);
  const [gateways, setGateways]     = useState([]);
  const [features, setFeatures]     = useState([]);
  const [mlPoints, setMlPoints]     = useState([]);
  const [uncertaintyPoints, setUncertaintyPoints] = useState([]);
  const [stats, setStats]           = useState(null);
  const [gridStatus, setGridStatus] = useState(null);

  const [mlRunning, setMlRunning] = useState(false);
  const [mlDone, setMlDone]       = useState(false);
  const [mlAlgorithm, setMlAlgorithm] = useState("idw");
  const [toast, setToast]         = useState(null);
  const [popupInfo, setPopupInfo] = useState(null);

  const [rssiMin, setRssiMin]     = useState(-120);
  const [sfFilter, setSfFilter]   = useState([7, 8, 9, 10, 11, 12]);
  const [hideUnreliable, setHideUnreliable] = useState(false);

  const [rssiConfig, setRssiConfig] = useState(null);
  const normalizer = rssiConfig?.normalizer ?? rssiToIntensity;

  const filteredFeatures = useMemo(() =>
    features.filter(f => {
      const p    = f?.properties;
      const rssi = p?.rssiDbm;
      const sf   = p?.spreadingFactor;
      const snr  = p?.snrDb;
      const rssiOk = rssi == null || rssi >= rssiMin;
      const sfOk   = sf   == null || sfFilter.includes(sf);
      const snrOk  = !hideUnreliable
                  || sf == null || snr == null
                  || snrMargin(snr, sf) > 0;
      return rssiOk && sfOk && snrOk;
    }),
  [features, rssiMin, sfFilter, hideUnreliable]);

  useEffect(() => {
    api.getCampaigns()
      .then(list => {
        const arr = Array.isArray(list) ? list : [];
        setCampaigns(arr.length > 0 ? arr : [{ id: DEFAULT_CAMPAIGN, name: S.app.defaultCampaignName }]);
      })
      .catch(err => {
        console.warn("[campaigns]", err.message);
        setCampaigns([{ id: DEFAULT_CAMPAIGN, name: S.app.defaultCampaignName }]);
      });

    api.getGateways()
      .then(list => setGateways(Array.isArray(list) ? list : []))
      .catch(err => {
        console.warn("[gateways]", err.message);
        setGateways([]);
      });
  }, []);

  // Khai báo TRƯỚC useEffect dùng nó để tránh TDZ.
  const loadMlGrid = useCallback((cid) => {
    api.getPredictionGrid(cid)
      .then(geojson => {
        const feats = geojson?.features ?? [];
        setMlPoints(feats.map(f => {
          const [lng, lat] = f.geometry.coordinates;
          return [lat, lng, f.properties.intensity ?? rssiToIntensity(f.properties.rssi ?? -100)];
        }));
        setUncertaintyPoints(feats.map(f => {
          const [lng, lat] = f.geometry.coordinates;
          return [lat, lng, f.properties.uncertainty ?? 0];
        }));
      })
      .catch(err => {
        console.warn("[prediction-grid]", err.message);
      });
  }, []);

  useEffect(() => {
    if (!campaignId) return;
    // Reset rssiConfig khi đổi campaign — intentional pattern
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRssiConfig(null);

    Promise.all([
      api.getMeasurements(campaignId),
      loadRssiConfig(campaignId),
    ])
      .then(([geojson, config]) => {
        setFeatures((geojson?.features ?? []).map(normalizeFeature));
        setRssiConfig(config);
      })
      .catch(err => {
        console.warn("[measurements]", err.message);
        setFeatures([]);
      });

    api.getStats(campaignId)
      .then(setStats)
      .catch(err => {
        console.warn("[stats]", err.message);
        setStats(null);
      });

    api.getPredictionStatus(campaignId)
      .then(s => {
        setGridStatus(s);
        if (s?.hasGrid) {
          setMlDone(true);
          loadMlGrid(campaignId);
        } else {
          setMlDone(false);
          setMlPoints([]);
          setUncertaintyPoints([]);
        }
      })
      .catch(err => {
        console.warn("[prediction-status]", err.message);
        setGridStatus(null);
      });
  }, [campaignId, loadMlGrid]);

  const handleRunML = useCallback(async () => {
    setMlRunning(true);
    try {
      // ML algo: train trước (nếu chưa có cached modelId), rồi run với mlModelId.
      // IDW/Kriging: run trực tiếp.
      let modelId = null;
      if (ML_ALGOS.has(mlAlgorithm)) {
        modelId = getCachedModelId(campaignId, mlAlgorithm);
        if (!modelId) {
          setToast("Đang train mô hình...");
          const trainRes = await api.trainModel(campaignId, mlAlgorithm);
          modelId = trainRes.modelId;
          setCachedModelId(campaignId, mlAlgorithm, modelId);
        }
      }

      setToast(S.app.toastRunning);
      const res = await api.runInterpolation(campaignId, mlAlgorithm, 50, modelId);
      setToast(S.app.toastDone(res.gridPoints?.toLocaleString(), res.durationSec));
      setMlDone(true);
      await loadMlGrid(campaignId);
      const s = await api.getPredictionStatus(campaignId);
      setGridStatus(s);
      setMode("ml-heat");
    } catch (e) {
      setToast(S.app.toastError(e.message));
    } finally {
      setMlRunning(false);
      setTimeout(() => setToast(null), 4000);
    }
  }, [campaignId, mlAlgorithm, loadMlGrid]);

  const filteredHeatPoints = useMemo(() =>
    filteredFeatures.map(f => {
      const [lng, lat] = f.geometry.coordinates;
      const rssi = f.properties.rssiDbm;
      return [lat, lng, normalizer(rssi), rssi];
    }),
    [filteredFeatures, normalizer]);

  useEffect(() => {
    if (!mapRef.current || !std) return;
    const map = mapRef.current.getMap();
    if (map?.setConfig) map.setConfig("basemap", { lightPreset });
  }, [lightPreset, std]);

  const handleMapClick = useCallback((e) => {
    if (mode !== "scatter") { setPopupInfo(null); return; }

    const feature = e.features?.[0];
    if (!feature) { setPopupInfo(null); return; }

    const nearest = findNearestGateway(e.lngLat.lat, e.lngLat.lng, gateways);
    setPopupInfo({
      longitude: e.lngLat.lng,
      latitude:  e.lngLat.lat,
      props:     feature.properties,
      nearest,
    });
  }, [mode, gateways]);

  const handleMouseEnter = useCallback((e) => {
    if (e.features?.length > 0) e.target.getCanvas().style.cursor = "pointer";
  }, []);
  const handleMouseLeave = useCallback((e) => {
    e.target.getCanvas().style.cursor = "";
  }, []);

  return (
    <div style={{ width: "100vw", height: "100vh", position: "relative", background: "#0f0f1a" }}>
      {/* NavBar tự position fixed top-center */}
      <NavBar />

      <Map
        ref={mapRef}
        id="main"
        mapboxAccessToken={TOKEN}
        initialViewState={{ ...DA_NANG, pitch: std ? 45 : 0, bearing: 0 }}
        mapStyle={mapStyle}
        config={std ? getConfig(lightPreset) : undefined}
        style={{ width: "100%", height: "100%" }}
        interactiveLayerIds={mode === "scatter" ? [SCATTER_LAYER_ID] : []}
        onClick={handleMapClick}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <NavigationControl position="bottom-right" visualizePitch />

        {mode === "scatter" && (
          <ScatterLayer
            features={filteredFeatures}
            popupInfo={popupInfo}
            onPopup={setPopupInfo}
            gateways={gateways}
          />
        )}
        {mode === "heat" && filteredHeatPoints.length > 0 && (
          <HeatmapLayer points={filteredHeatPoints} />
        )}
        {mode === "ml-heat" && mlPoints.length > 0 && (
          <MLGridLayer points={mlPoints} radius={30} />
        )}
        {mode === "uncertainty" && uncertaintyPoints.length > 0 && (
          <UncertaintyLayer points={uncertaintyPoints} radius={30} />
        )}

        {showGateways && (
          <GatewayMarkers
            gateways={gateways}
            showRangeCircles={showRangeCircles}
            rangeKm={rangeKm}
          />
        )}
      </Map>

      <Toolbar
        mode={mode}                         onMode={setMode}
        campaignId={campaignId}             onCampaign={setCampaignId}
        campaigns={campaigns}
        onRunML={handleRunML}   mlRunning={mlRunning}   mlDone={mlDone}
        mlAlgorithm={mlAlgorithm}           onMlAlgorithm={setMlAlgorithm}
        showGateways={showGateways}         onToggleGateways={() => setShowGateways(v => !v)}
        showRangeCircles={showRangeCircles} onToggleRangeCircles={() => setShowRangeCircles(v => !v)}
        rangeKm={rangeKm}                   onRangeKm={setRangeKm}
        mapStyle={mapStyle}                 onMapStyle={setMapStyle}
        lightPreset={lightPreset}           onLightPreset={setLightPreset}
        rssiMin={rssiMin}                   onRssiMin={setRssiMin}
        sfFilter={sfFilter}                 onSfFilter={setSfFilter}
        hideUnreliable={hideUnreliable}     onToggleHideUnreliable={() => setHideUnreliable(v => !v)}
      />

      <StatsPanel
        stats={stats}
        gridStatus={gridStatus}
        mode={mode}
        pointCount={features.length}
        features={features}
      />

      {toast && (
        <div style={{
          position: "absolute", bottom: 24, left: "50%", transform: "translateX(-50%)",
          background: "rgba(20,20,30,0.95)", color: "#f9fafb",
          padding: "10px 20px", borderRadius: 10, fontSize: 13,
          border: "1px solid rgba(255,255,255,0.15)", zIndex: 2000,
          backdropFilter: "blur(8px)", maxWidth: "80vw", textAlign: "center",
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}