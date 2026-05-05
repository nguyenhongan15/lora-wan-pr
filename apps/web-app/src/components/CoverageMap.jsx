// @ts-check
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { listGateways, listSurveyTraining } from "../api/client.js";

const DANANG_BBOX = {
  min_lon: 107.95,
  min_lat: 15.9,
  max_lon: 108.4,
  max_lat: 16.2,
};

const INITIAL_CENTER = /** @type {[number, number]} */ ([108.18, 16.05]);
const INITIAL_ZOOM = 10;

/**
 * @param {number} rssi
 */
function rssiColor(rssi) {
  if (rssi >= -100) return "#16a34a";
  if (rssi >= -110) return "#eab308";
  if (rssi >= -120) return "#f97316";
  return "#dc2626";
}

const OSM_RASTER_STYLE = {
  version: 8,
  sources: {
    basemap: {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      maxzoom: 19,
    },
  },
  layers: [{ id: "basemap", type: "raster", source: "basemap" }],
};

export function CoverageMap() {

  function Legend({ gatewayCount, surveyCount }) {
    return (
      <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm">
        <div className="mb-2 text-xs text-slate-500">
          {gatewayCount ?? "…"} gateway · {surveyCount ?? "…"} điểm đo
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-3 w-3 rotate-45 border border-white bg-blue-700 shadow" />
            Gateway
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-600" />
            ≥ -100
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-yellow-500" />
            ≥ -110
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-orange-500" />
            ≥ -120
          </span>
          <span className="inline-flex items-center gap-2">
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-600" />
            không phủ
          </span>
        </div>
      </div>
    );
  }

  const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null));
  const mapRef = useRef(/** @type {maplibregl.Map | null} */ (null));
  const markersRef = useRef(/** @type {maplibregl.Marker[]} */ ([]));
  const [tileError, setTileError] = useState(/** @type {string | null} */ (null));

  const gatewaysQ = useQuery({
    queryKey: ["gateways", DANANG_BBOX],
    queryFn: () => listGateways(DANANG_BBOX),
  });

  const surveysQ = useQuery({
    queryKey: ["surveys", DANANG_BBOX],
    queryFn: () => listSurveyTraining(DANANG_BBOX),
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container || mapRef.current) return;

    let map;
    try {
      map = new maplibregl.Map({
        container,
        style: /** @type {any} */ (OSM_RASTER_STYLE),
        center: INITIAL_CENTER,
        zoom: INITIAL_ZOOM,
      });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTileError(`Map init failed: ${msg}`);
      return;
    }

    map.addControl(new maplibregl.NavigationControl({}), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    map.on("error", (e) => {
      const msg = e?.error?.message ?? String(e);
      setTileError(msg);
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (!gatewaysQ.data && !surveysQ.data) return;

    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    if (surveysQ.data) {
      for (const p of surveysQ.data.items) {
        const el = document.createElement("div");
        el.style.width = "10px";
        el.style.height = "10px";
        el.style.borderRadius = "50%";
        el.style.background = rssiColor(p.rssi_dbm);
        el.style.border = "1px solid white";
        el.style.boxShadow = "0 0 2px rgba(0,0,0,0.4)";
        const popup = new maplibregl.Popup({ offset: 8 }).setHTML(
          `<div style="font:12px/1.4 system-ui">
             <div><strong>Survey point</strong></div>
             <div>RSSI: ${p.rssi_dbm.toFixed(1)} dBm</div>
             <div>SNR: ${p.snr_db.toFixed(1)} dB</div>
             <div>SF${p.spreading_factor}</div>
           </div>`,
        );
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([p.longitude, p.latitude])
          .setPopup(popup)
          .addTo(map);
        markersRef.current.push(marker);
      }
    }

    if (gatewaysQ.data) {
      for (const g of gatewaysQ.data.items) {
        const el = document.createElement("div");
        el.style.width = "16px";
        el.style.height = "16px";
        el.style.background = "#1d4ed8";
        el.style.border = "2px solid white";
        el.style.boxShadow = "0 0 4px rgba(0,0,0,0.5)";
        el.style.transform = "rotate(45deg)";
        const popup = new maplibregl.Popup({ offset: 12 }).setHTML(
          `<div style="font:12px/1.4 system-ui">
             <div><strong>${g.code}</strong> — ${g.name}</div>
             <div>TX: ${g.tx_power_dbm} dBm, gain ${g.antenna_gain_dbi} dBi</div>
             <div>Antenna: ${g.antenna_height_m} m AGL</div>
             <div>Freq: ${g.frequency_mhz} MHz</div>
           </div>`,
        );
        const marker = new maplibregl.Marker({ element: el })
          .setLngLat([g.longitude, g.latitude])
          .setPopup(popup)
          .addTo(map);
        markersRef.current.push(marker);
      }
    }
  }, [gatewaysQ.data, surveysQ.data]);

  return (
    <div className="h-full w-full">
  <div className="relative h-full w-full overflow-hidden">
        <div ref={containerRef} className="h-full w-full" />
  
        <div className="absolute top-3 left-3 z-10">
          <div className="rounded-md border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-sm">
            
            <div className="mb-2 text-xs text-slate-500">
              {gatewaysQ.data?.total ?? "…"} gateway ·{" "}
              {surveysQ.data?.total ?? "…"} điểm đo
            </div>
            <div className="flex flex-col gap-1.5">
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-3 w-3 rotate-45 border border-white bg-blue-700 shadow" />
                Gateway
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-600" />
                ≥ -100
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-yellow-500" />
                ≥ -110
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-orange-500" />
                ≥ -120
              </span>
              <span className="inline-flex items-center gap-2">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-600" />
                không phủ
              </span>
            </div>
          </div>
        </div>
  
        {(gatewaysQ.isError || surveysQ.isError) && (
          <div className="absolute right-3 top-3 z-10 max-w-sm rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 shadow-md">
            Không tải được dữ liệu API. Kiểm tra api-service đang chạy chưa
            (http://localhost:8000/healthz).
          </div>
        )}
  
        {tileError && (
          <div className="absolute bottom-3 right-3 z-10 max-w-sm rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 shadow-md">
            <div className="font-semibold">Tile không load được</div>
            <div className="mt-1">{tileError}</div>
          </div>
        )}
      </div>
    </div>
  );
}