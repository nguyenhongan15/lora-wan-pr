// @ts-check
// Landing page — Mapbox-inspired light layout, deep-blue accent.
// Ported từ codetmp/styles.css + LPWAN Landing.html + map-svg.js (đã xoá codetmp).
// Tất cả CSS scope dưới .landing-root để không leak ra phần còn lại của app.

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";

import { listGateways, listSurveyTraining } from "../api/client.js";
import {
  BASEMAP_STYLE,
  INITIAL_CENTER,
  RSSI_FILL_OPACITY,
} from "./CoverageMap.config.js";
import {
  ESTIMATE_RSSI_BAND_COLORS,
  surveyRssiColorExpression,
} from "./legend.js";
import { strings } from "../strings.js";
import "./LandingPage.css";

const t = strings.landing;

/** @typedef {import("../App.jsx").Tab} Tab */

/**
 * @param {{
 *   onNavigate: (next: Tab, subTab?: string) => void,
 *   isLoggedIn: boolean,
 *   onRequestLogin: (afterLogin?: () => void) => void,
 * }} props
 */
export function LandingPage({ onNavigate, isLoggedIn, onRequestLogin }) {
  const scrollTo = (/** @type {string} */ id) => {
    const el = typeof document !== "undefined" ? document.getElementById(id) : null;
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="landing-root">
      <Hero onNavigate={onNavigate} onScrollTo={scrollTo} />
      <How />
      <Features
        onNavigate={onNavigate}
        isLoggedIn={isLoggedIn}
        onRequestLogin={onRequestLogin}
      />
      <Faq />
      <Cta
        onNavigate={onNavigate}
        isLoggedIn={isLoggedIn}
        onRequestLogin={onRequestLogin}
      />
      <FooterBlock onNavigate={onNavigate} />
    </div>
  );
}

/** @param {{ onNavigate: (next: Tab) => void, onScrollTo: (id: string) => void }} props */
function Hero({ onNavigate, onScrollTo }) {
  return (
    <section className="hero">
      <div className="container hero-grid">
        <div className="hero-text reveal">
          <span className="eyebrow">{t.hero.eyebrow}</span>
          <h1 className="display">
            {t.hero.titleStart}
            <em style={{ color: "var(--accent)", fontStyle: "normal" }}>
              {t.hero.titleEm}
            </em>
            {t.hero.titleEnd}
          </h1>
          <p className="lede">{t.hero.lede}</p>
          <div className="hero-cta">
            <button
              type="button"
              className="btn btn-accent"
              onClick={() => onNavigate("heatmap")}
            >
              {t.hero.ctaPrimary} <span className="arrow">→</span>
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onScrollTo("lp-how")}
            >
              {t.hero.ctaSecondary}
            </button>
          </div>
          <div className="hero-meta">
            {t.hero.stats.map((s, i) => (
              <div key={i} className="hero-stat">
                <span className="v">{s.v}</span>
                <span className="k">{s.k}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="hero-map reveal" data-delay="1">
          <div className="mockwin hero-mockwin">
            <div className="mockwin-bar">
              <div className="dots">
                <span />
                <span />
                <span />
              </div>
              <span className="url">{t.hero.mockUrl}</span>
            </div>
            <div className="mockwin-body">
              <LiveMapPanel />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function How() {
  return (
    <section id="lp-how" className="section">
      <div className="container">
        <div className="section-head reveal">
          <div>
            <span className="eyebrow">{t.how.eyebrow}</span>
            <h2 className="display">{t.how.title}</h2>
          </div>
          <p className="lede">{t.how.lede}</p>
        </div>
        <div className="steps">
          {t.how.steps.map((s, i) => (
            <div
              key={s.num}
              className="step reveal"
              data-delay={String(i + 1)}
            >
              <div className="num">{s.num}</div>
              <h3>{s.title}</h3>
              <p>{s.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/**
 * @param {{
 *   onNavigate: (next: Tab, subTab?: string) => void,
 *   isLoggedIn: boolean,
 *   onRequestLogin: (afterLogin?: () => void) => void,
 * }} props
 */
function Features({ onNavigate, isLoggedIn, onRequestLogin }) {
  return (
    <section className="section">
      <div className="container">
        <div className="section-head reveal">
          <div>
            <span className="eyebrow">{t.features.eyebrow}</span>
            <h2 className="display">{t.features.title}</h2>
          </div>
          <p className="lede">{t.features.lede}</p>
        </div>
        <div className="features">
          {t.features.items.map((f, i) => (
            <FeatureRow
              key={f.num}
              feature={f}
              index={i}
              reverse={i % 2 === 1}
              onNavigate={onNavigate}
              isLoggedIn={isLoggedIn}
              onRequestLogin={onRequestLogin}
            />
          ))}
        </div>
      </div>
    </section>
  );
}

/**
 * @param {{
 *   feature: typeof strings.landing.features.items[number],
 *   index: number,
 *   reverse: boolean,
 *   onNavigate: (next: Tab, subTab?: string) => void,
 *   isLoggedIn: boolean,
 *   onRequestLogin: (afterLogin?: () => void) => void,
 * }} props
 */
function FeatureRow({ feature, index, reverse, onNavigate, isLoggedIn, onRequestLogin }) {
  // F·05/F·06 (target=sources) yêu cầu đăng nhập. Chưa login → mở AuthModal
  // kèm afterLogin → effect ở App fire navigate sau khi user truthy. Đã login
  // → navigate trực tiếp về Sources/<subTab>.
  const tab = /** @type {Tab} */ (feature.target);
  const subTab = /** @type {string | undefined} */ (
    /** @type {any} */ (feature).subTab
  );
  const handleClick = () => {
    if (tab === "sources" && !isLoggedIn) {
      onRequestLogin(() => onNavigate(tab, subTab));
      return;
    }
    onNavigate(tab, subTab);
  };
  return (
    <div className={`feature reveal${reverse ? " reverse" : ""}`}>
      <div className="feature-text">
        <span className="eyebrow">{feature.num}</span>
        <h3>{feature.title}</h3>
        <p>{feature.desc}</p>
        <button
          type="button"
          className="btn btn-accent btn-sm feature-cta"
          onClick={handleClick}
        >
          {feature.cta} <span className="arrow">→</span>
        </button>
      </div>
      <div className="feature-mock">
        <div className="mockwin">
          <div className="mockwin-bar">
            <div className="dots">
              <span />
              <span />
              <span />
            </div>
            <span className="url">{feature.mockUrl}</span>
          </div>
          <div className="mockwin-body">
            {/* index 0 (heatmap) = real coverage preview; index 1 (survey) = real
                survey-points preview; index 2 (predict) = pin + result card mock;
                index 3 (F·04 theo dõi trực tiếp) = ảnh minh hoạ; index 4 (sources)
                = source-cards mock; index 5 (contribute) = pipeline mock. */}
            {index === 0 ? (
              <LiveMapPanel />
            ) : index === 1 ? (
              <FeatureSurveyMapPanel />
            ) : index === 2 ? (
              <div className="mini-map">
                <img
                  className="feat-predict-img"
                  src={`${import.meta.env.BASE_URL ?? "/"}f3_landingpage.svg`}
                  alt="Minh hoạ kết quả dự đoán tín hiệu tại một vị trí trên bản đồ"
                  loading="lazy"
                />
              </div>
            ) : index === 3 ? (
              <div className="mini-map">
                <img
                  className="feat-predict-img"
                  src={`${import.meta.env.BASE_URL ?? "/"}f4_landingpage.png`}
                  alt="Minh hoạ theo dõi trực tiếp chuyến đi khảo sát trên bản đồ"
                  loading="lazy"
                />
              </div>
            ) : index === 4 ? (
              <FeatureSourcesMock />
            ) : index === 5 ? (
              <FeatureContributeMock />
            ) : (
              <div className="mini-map">
                <DaNangMapSvg id={`lp-feat-${index}`} withGlow />
                <Markers
                  surveys={COMPACT_SURVEYS.slice(0, 3)}
                  gateways={DEFAULT_GATEWAYS.slice(0, 1)}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Faq() {
  return (
    <section className="section">
      <div className="container">
        <div className="section-head reveal">
          <div>
            <span className="eyebrow">{t.faq.eyebrow}</span>
            <h2 className="display">{t.faq.title}</h2>
          </div>
          <p className="lede">{t.faq.lede}</p>
        </div>
        <div className="faq-list">
          {t.faq.items.map((item, i) => (
            <details key={i} className="faq-item">
              <summary className="faq-q">
                <span>{item.q}</span>
                <span className="plus" aria-hidden>
                  +
                </span>
              </summary>
              <p className="faq-a">{item.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

/**
 * @param {{
 *   onNavigate: (next: Tab) => void,
 *   isLoggedIn: boolean,
 *   onRequestLogin: () => void,
 * }} props
 */
function Cta({ onNavigate, isLoggedIn, onRequestLogin }) {
  return (
    <section className="section">
      <div className="container">
        <div className="cta-strip reveal">
          <div>
            <h2 className="display">{t.cta.title}</h2>
            <p>{t.cta.desc}</p>
          </div>
          <div className="cta-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onNavigate("heatmap")}
            >
              {t.cta.primary} <span className="arrow">→</span>
            </button>
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() =>
                isLoggedIn ? onNavigate("sources") : onRequestLogin()
              }
            >
              {isLoggedIn ? t.cta.secondaryLoggedIn : t.cta.secondary}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

/** @param {{ onNavigate: (next: Tab) => void }} props */
function FooterBlock({ onNavigate }) {
  return (
    <footer className="lp-footer">
      <div className="container">
        <div className="foot-grid">
          <div className="foot-brand">
            <div className="brand">
              <span className="brand-mark">LM</span>
              <span>LoRa Coverage Map</span>
            </div>
            <p>{t.footer.desc}</p>
          </div>
          {t.footer.cols.map((col, i) => (
            <div key={i}>
              <h5>{col.h}</h5>
              <ul>
                {col.items.map((it, j) =>
                  it.target ? (
                    <li key={j}>
                      <button
                        type="button"
                        onClick={() =>
                          onNavigate(/** @type {Tab} */ (it.target))
                        }
                      >
                        {it.label}
                      </button>
                    </li>
                  ) : (
                    <li key={j} className="disabled">
                      {it.label}
                    </li>
                  ),
                )}
              </ul>
            </div>
          ))}
        </div>
        <div className="foot-meta">
          <span>{t.footer.copyright}</span>
          <span>{t.footer.version}</span>
        </div>
      </div>
    </footer>
  );
}

/* ---------- Live map panel (MapLibre + chrome + legend) ---------- */

/**
 * Khung "map-frame live" tái sử dụng cho cả hero và feature #1, đảm bảo
 * 2 chỗ trông y hệt nhau (1 MapLibre instance riêng, chip topbar, legend).
 */
function LiveMapPanel() {
  return (
    <div className="map-frame live">
      <HeroLiveMap />
      <div className="map-chrome">
        <div className="topbar">
          <span className="chip">
            <span className="dot" />
            {t.hero.mapLive}
          </span>
          <span className="chip">{t.hero.mapLayer}</span>
        </div>
      </div>
      <div className="legend">
        <span className="title">{t.hero.mapLegendTitle}</span>
        <div className="legend-bar" />
        <div className="legend-ticks">
          <span>-120</span>
          <span>-115</span>
          <span>-110</span>
          <span>-105</span>
          <span>-100</span>
        </div>
      </div>
    </div>
  );
}

/* ---------- Hero live map (MapLibre embed) ---------- */

// Kerlink iStation AEC — community gateway. Per-gw heatmap + radar 25 km
// sweep được căn theo chính gateway này (cùng artifact dùng cho tab "Bản đồ
// phủ sóng" khi chọn 1 gateway).
const HERO_GATEWAY_CODE = "7276ff000b031aec";

/**
 * Real MapLibre instance cho hero, dùng cùng BASEMAP_STYLE (CARTO Voyager)
 * như tab "Bản đồ phủ sóng". Layer chính = per-gateway RSSI heatmap của
 * Kerlink iStation AEC, load từ public/coverage/rssi/per_gw/<code>.geojson —
 * cùng artifact CoverageMap dùng cho mode "estimate" + estimateGatewayCode.
 * Silent fail khi API offline — basemap vẫn render.
 */
function HeroLiveMap() {
  const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null));

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    /** @type {maplibregl.Map} */
    let map;
    try {
      map = new maplibregl.Map({
        container,
        style: /** @type {any} */ (BASEMAP_STYLE),
        center: INITIAL_CENTER,
        zoom: 10.8,
        interactive: false,
        attributionControl: { compact: true },
        cooperativeGestures: false,
      });
    } catch {
      return undefined;
    }

    let cancelled = false;
    /** @type {maplibregl.Marker[]} */
    const markers = [];
    let pulseRafId = 0;

    map.on("load", async () => {
      if (cancelled) return;
      const b = map.getBounds();
      const bbox = {
        min_lon: b.getWest(),
        min_lat: b.getSouth(),
        max_lon: b.getEast(),
        max_lat: b.getNorth(),
      };
      try {
        const base = import.meta.env.BASE_URL ?? "/";
        const [gwResp, perGwResp] = await Promise.all([
          listGateways(bbox, { contributor: "community" }),
          fetch(`${base}coverage/rssi/per_gw/${HERO_GATEWAY_CODE}.geojson`).then(
            (r) => (r.ok ? r.json() : null),
          ),
        ]);
        if (cancelled) return;

        // Per-gateway RSSI heatmap (1 gateway). Fill layer add TRƯỚC marker để
        // gateway pulse nằm trên cùng. Paint match: bin 1..6 → palette
        // ESTIMATE_RSSI_BAND_COLORS (shared với tab "Bản đồ phủ sóng" estimate).
        if (perGwResp && Array.isArray(perGwResp.features)) {
          map.addSource("lp-rssi-composite", {
            type: "geojson",
            data: perGwResp,
          });
          map.addLayer({
            id: "lp-rssi-composite-fill",
            type: "fill",
            source: "lp-rssi-composite",
            layout: /** @type {any} */ ({
              "fill-sort-key": ["-", 7, ["get", "bin"]],
            }),
            paint: /** @type {any} */ ({
              "fill-color": [
                "match",
                ["get", "bin"],
                1, ESTIMATE_RSSI_BAND_COLORS[1],
                2, ESTIMATE_RSSI_BAND_COLORS[2],
                3, ESTIMATE_RSSI_BAND_COLORS[3],
                4, ESTIMATE_RSSI_BAND_COLORS[4],
                5, ESTIMATE_RSSI_BAND_COLORS[5],
                6, ESTIMATE_RSSI_BAND_COLORS[6],
                "#888888",
              ],
              "fill-opacity": RSSI_FILL_OPACITY,
            }),
          });
        }

        // Chỉ hiện 1 marker cho gateway AEC — match cả layer phủ sóng phía
        // dưới. State filter bỏ vì community gw có thể không có ChirpStack
        // monitoring → state undefined.
        const aecGw = (gwResp.items ?? []).find(
          (gw) =>
            gw.code === HERO_GATEWAY_CODE &&
            gw.latitude != null &&
            gw.longitude != null,
        );
        if (aecGw) {
          const el = document.createElement("span");
          el.className = "lp-libre-gw";
          el.setAttribute("aria-hidden", "true");
          const m = new maplibregl.Marker({ element: el })
            .setLngLat([aecGw.longitude, aecGw.latitude])
            .addTo(map);
          markers.push(m);

          // Ring 15 km georeferenced: circle layer thay cho .lp-libre-gw::after
          // (CSS scale screen-space, không bám km). Radius_px tính lại mỗi
          // frame theo map.getZoom() → giữ đúng 15 km khi zoom đổi.
          map.addSource("lp-gw-pulse-src", {
            type: "geojson",
            data: {
              type: "Feature",
              properties: {},
              geometry: {
                type: "Point",
                coordinates: [aecGw.longitude, aecGw.latitude],
              },
            },
          });
          map.addLayer({
            id: "lp-gw-pulse-ring",
            type: "circle",
            source: "lp-gw-pulse-src",
            paint: /** @type {any} */ ({
              "circle-radius": 0,
              "circle-color": "rgba(0,0,0,0)",
              "circle-stroke-width": 1.5,
              "circle-stroke-color": "rgba(29,95,209,0.65)",
              "circle-stroke-opacity": 0,
            }),
          });

          const PERIOD_MS = 3600;
          const TARGET_M = 15000;
          const latRad = (aecGw.latitude * Math.PI) / 180;
          const startMs = performance.now();
          const tick = (/** @type {number} */ now) => {
            if (cancelled) return;
            // RAF timestamp có thể < startMs → clamp tránh phase âm.
            const elapsed = Math.max(0, now - startMs);
            const phase = (elapsed % PERIOD_MS) / PERIOD_MS;
            // m/px tại zoom hiện tại + lat AEC: Web Mercator formula.
            const mPerPx =
              (40075016.686 * Math.cos(latRad)) /
              (Math.pow(2, map.getZoom()) * 256);
            const radiusPx = Math.max(0, (TARGET_M * phase) / mPerPx);
            const opacity = 0.65 * Math.pow(1 - phase, 1.2);
            map.setPaintProperty(
              "lp-gw-pulse-ring",
              "circle-radius",
              radiusPx,
            );
            map.setPaintProperty(
              "lp-gw-pulse-ring",
              "circle-stroke-opacity",
              opacity,
            );
            pulseRafId = requestAnimationFrame(tick);
          };
          pulseRafId = requestAnimationFrame(tick);
        }
      } catch {
        // API offline / CORS — basemap mode only, không break landing.
      }
    });

    return () => {
      cancelled = true;
      if (pulseRafId) cancelAnimationFrame(pulseRafId);
      for (const m of markers) m.remove();
      map.remove();
    };
  }, []);

  return <div ref={containerRef} className="map-canvas" />;
}

/* ---------- F·02 live survey map preview ---------- */

/**
 * Preview cho F·02 ("Bản đồ điểm đo khảo sát thực địa"). Render trong cùng frame
 * `.map-frame.live` như hero để styling đồng nhất (aspect-ratio 16/11 trong
 * feature-mock). Không legend chrome — preview gọn, người dùng nhấn CTA mới vào
 * tab thật xem chi tiết.
 */
function FeatureSurveyMapPanel() {
  return (
    <div className="map-frame live">
      <FeatureSurveyMap />
    </div>
  );
}

/**
 * Real MapLibre instance load survey points + gateway community như tab "Bản đồ
 * điểm đo" — nhưng không tương tác (interactive=false, no popup). Silent fail
 * khi API offline → basemap-only.
 */
function FeatureSurveyMap() {
  const containerRef = useRef(/** @type {HTMLDivElement | null} */ (null));

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    /** @type {maplibregl.Map} */
    let map;
    try {
      map = new maplibregl.Map({
        container,
        style: /** @type {any} */ (BASEMAP_STYLE),
        center: INITIAL_CENTER,
        zoom: 10.6,
        interactive: false,
        attributionControl: { compact: true },
        cooperativeGestures: false,
      });
    } catch {
      return undefined;
    }

    let cancelled = false;

    // Container ở trong feature-mock grid (aspect-ratio 16/11) có thể resize sau
    // initial paint → MapLibre giữ size cũ, projection lệch khỏi tile thật.
    // ResizeObserver call map.resize() để re-project survey points đúng vị trí.
    const ro = new ResizeObserver(() => {
      if (cancelled) return;
      map.resize();
    });
    ro.observe(container);

    map.on("load", async () => {
      if (cancelled) return;
      map.resize();
      const b = map.getBounds();
      const bbox = {
        min_lon: b.getWest(),
        min_lat: b.getSouth(),
        max_lon: b.getEast(),
        max_lat: b.getNorth(),
      };
      try {
        const surveyResp = await listSurveyTraining(bbox, {
          contributor: "community",
        });
        if (cancelled) return;

        // Survey circles — paint expression theo RSSI bin (dùng chung với tab
        // "Bản đồ điểm đo"). Radius nhỏ hơn (3 thay vì 4) để preview gọn.
        const features = (surveyResp.items ?? [])
          .filter((s) => s.latitude != null && s.longitude != null)
          .map((s) => ({
            type: /** @type {"Feature"} */ ("Feature"),
            geometry: {
              type: /** @type {"Point"} */ ("Point"),
              coordinates: [s.longitude, s.latitude],
            },
            properties: { rssi_dbm: s.rssi_dbm },
          }));
        map.addSource("lp-survey-src", {
          type: "geojson",
          data: { type: "FeatureCollection", features },
        });
        map.addLayer({
          id: "lp-survey-layer",
          type: "circle",
          source: "lp-survey-src",
          paint: /** @type {any} */ ({
            "circle-radius": 3,
            "circle-color": surveyRssiColorExpression(),
            "circle-stroke-width": 0.5,
            "circle-stroke-color": "#ffffff",
          }),
        });
      } catch {
        // API offline / CORS — basemap mode only, không break landing.
      }
    });

    return () => {
      cancelled = true;
      ro.disconnect();
      map.remove();
    };
  }, []);

  return <div ref={containerRef} className="map-canvas" />;
}

/**
 * F·05 preview — stack of source cards mô phỏng UI Tổng quan trong "Dữ liệu
 * của tôi". Hiển thị 3 nguồn: Lpwanmapper (bản ghi), ChirpStack (live webhook),
 * CSV upload (batch đã duyệt). Status dot xanh = active, xám = idle.
 */
function FeatureSourcesMock() {
  return (
    <div className="feat-sources-mock">
      <div className="feat-sources-mock-head">
        <span className="feat-sources-mock-title">Nguồn dữ liệu của tôi</span>
        <span className="feat-sources-mock-badge">3 nguồn</span>
      </div>
      <div className="feat-sources-mock-list">
        <div className="feat-sources-mock-card">
          <span className="feat-sources-mock-dot is-active" aria-hidden="true" />
          <div className="feat-sources-mock-body">
            <div className="feat-sources-mock-name">Lpwanmapper</div>
            <div className="feat-sources-mock-meta">1,245 bản ghi · cập nhật 2 phút trước</div>
          </div>
          <span className="feat-sources-mock-tag is-live">Đang đồng bộ</span>
        </div>
        <div className="feat-sources-mock-card">
          <span className="feat-sources-mock-dot is-active" aria-hidden="true" />
          <div className="feat-sources-mock-body">
            <div className="feat-sources-mock-name">ChirpStack</div>
            <div className="feat-sources-mock-meta">Webhook live · 320 gói/giờ</div>
          </div>
          <span className="feat-sources-mock-tag is-live">Hoạt động</span>
        </div>
        <div className="feat-sources-mock-card">
          <span className="feat-sources-mock-dot is-idle" aria-hidden="true" />
          <div className="feat-sources-mock-body">
            <div className="feat-sources-mock-name">CSV upload</div>
            <div className="feat-sources-mock-meta">2 batch · 487 điểm đo</div>
          </div>
          <span className="feat-sources-mock-tag">Đã duyệt</span>
        </div>
      </div>
    </div>
  );
}

/**
 * F·06 preview — pipeline 4 bước đóng góp dữ liệu + counter cộng đồng. Mỗi
 * step có icon + nhãn, connector giữa các step cho cảm giác flow. Counter ở
 * trên cùng tạo motivational hook ("đóng góp của bạn đi vào dataset chung").
 */
function FeatureContributeMock() {
  return (
    <div className="feat-contrib-mock">
      <div className="feat-contrib-mock-stat">
        <div className="feat-contrib-mock-stat-val">10 000+</div>
        <div className="feat-contrib-mock-stat-lbl">điểm đo đã được đóng góp</div>
      </div>
    </div>
  );
}

/* ---------- Đà Nẵng map preview SVG (dùng cho feature mockwins) ---------- */

/** @param {{ id: string, withGlow?: boolean }} props */
function DaNangMapSvg({ id, withGlow = true }) {
  return (
    <svg
      className="map-canvas map-svg"
      viewBox="0 0 400 500"
      preserveAspectRatio="xMidYMid slice"
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={`${id}-ocean`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0a1224" />
          <stop offset="100%" stopColor="#070d1a" />
        </linearGradient>
        <linearGradient id={`${id}-land`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#1f273f" />
          <stop offset="100%" stopColor="#161d31" />
        </linearGradient>
        <radialGradient id={`${id}-glow-g`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#16a34a" stopOpacity="0.85" />
          <stop offset="60%" stopColor="#16a34a" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#16a34a" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-glow-y`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#eab308" stopOpacity="0.85" />
          <stop offset="60%" stopColor="#eab308" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#eab308" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-glow-o`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#f97316" stopOpacity="0.8" />
          <stop offset="60%" stopColor="#f97316" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#f97316" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-glow-r`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#dc2626" stopOpacity="0.75" />
          <stop offset="60%" stopColor="#dc2626" stopOpacity="0.14" />
          <stop offset="100%" stopColor="#dc2626" stopOpacity="0" />
        </radialGradient>
        <pattern
          id={`${id}-grid`}
          width="20"
          height="20"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M 20 0 L 0 0 0 20"
            fill="none"
            stroke="rgba(255,255,255,0.025)"
            strokeWidth="1"
          />
        </pattern>
      </defs>

      <rect width="400" height="500" fill={`url(#${id}-ocean)`} />
      <rect width="400" height="500" fill={`url(#${id}-grid)`} />

      {/* Mainland (stylized) */}
      <path
        d="M 0 60 L 90 50 L 140 80 L 170 70 L 200 100 L 230 95 L 245 130 L 235 170 L 250 200 L 245 240 L 260 280 L 250 330 L 245 380 L 230 430 L 215 470 L 200 500 L 0 500 Z"
        fill={`url(#${id}-land)`}
        stroke="rgba(120,140,180,0.25)"
        strokeWidth="1"
      />

      {/* Sơn Trà peninsula */}
      <path
        d="M 240 50 L 290 40 L 340 55 L 370 80 L 380 110 L 360 140 L 320 150 L 280 135 L 250 110 L 235 80 Z"
        fill={`url(#${id}-land)`}
        stroke="rgba(120,140,180,0.3)"
        strokeWidth="1"
      />

      {/* East coastline highlight */}
      <path
        d="M 245 130 L 235 170 L 250 200 L 245 240 L 260 280 L 250 330 L 245 380 L 230 430 L 215 470"
        fill="none"
        stroke="rgba(180,200,240,0.18)"
        strokeWidth="1.5"
      />

      {/* Hàn river */}
      <path
        d="M 200 100 Q 198 180, 210 230 Q 215 280, 208 340 Q 205 400, 215 470"
        fill="none"
        stroke="rgba(60,100,180,0.55)"
        strokeWidth="6"
        strokeLinecap="round"
      />
      <path
        d="M 200 100 Q 198 180, 210 230 Q 215 280, 208 340 Q 205 400, 215 470"
        fill="none"
        stroke="rgba(120,170,240,0.25)"
        strokeWidth="1.5"
        strokeLinecap="round"
        data-river-shimmer=""
      />

      {/* Bay between Sơn Trà and mainland */}
      <path
        d="M 235 80 Q 230 110 245 130 L 230 95 L 200 100 Z"
        fill="rgba(20,30,55,0.6)"
      />

      {/* Major road hints */}
      <g stroke="rgba(180,200,240,0.09)" strokeWidth="1" fill="none">
        <path d="M 50 200 L 200 210" />
        <path d="M 80 290 L 210 295" />
        <path d="M 100 380 L 215 385" />
        <path d="M 150 100 L 160 470" />
        <path d="M 100 110 L 110 480" />
        <path d="M 220 250 L 245 245" />
      </g>

      {withGlow ? (
        <>
          <circle cx="180" cy="220" r="80" fill={`url(#${id}-glow-g)`} />
          <circle cx="120" cy="320" r="70" fill={`url(#${id}-glow-g)`} />
          <circle cx="270" cy="90" r="55" fill={`url(#${id}-glow-y)`} />
          <circle cx="230" cy="280" r="60" fill={`url(#${id}-glow-y)`} />
          <circle cx="60" cy="160" r="50" fill={`url(#${id}-glow-o)`} />
          <circle cx="180" cy="430" r="65" fill={`url(#${id}-glow-o)`} />
          <circle cx="40" cy="430" r="55" fill={`url(#${id}-glow-r)`} />
          <circle cx="320" cy="115" r="40" fill={`url(#${id}-glow-r)`} />
        </>
      ) : null}
    </svg>
  );
}

/* ---------- Marker overlay (absolute % within map-frame) ---------- */

const COMPACT_SURVEYS = /** @type {const} */ ([
  { x: 50, y: 50, c: "var(--sig-excellent)" },
  { x: 42, y: 58, c: "var(--sig-good)" },
  { x: 60, y: 45, c: "var(--sig-fair)" },
  { x: 35, y: 70, c: "var(--sig-poor)" },
  { x: 65, y: 65, c: "var(--sig-bad)" },
]);

const DEFAULT_GATEWAYS = /** @type {const} */ ([
  { x: 45, y: 44 },
  { x: 30, y: 65 },
  { x: 65, y: 20 },
]);

/**
 * @param {{
 *   surveys: readonly { x: number, y: number, c: string }[],
 *   gateways: readonly { x: number, y: number }[],
 * }} props
 */
function Markers({ surveys, gateways }) {
  return (
    <>
      {surveys.map((s, i) => (
        <span
          key={`s${i}`}
          className="marker"
          style={/** @type {React.CSSProperties} */ (
            /** @type {unknown} */ ({
              left: `${s.x}%`,
              top: `${s.y}%`,
              background: s.c,
              "--i": i,
            })
          )}
        />
      ))}
      {gateways.map((g, i) => (
        <span
          key={`g${i}`}
          className="marker gw"
          style={{ left: `${g.x}%`, top: `${g.y}%` }}
        />
      ))}
    </>
  );
}
