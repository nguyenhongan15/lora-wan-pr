/**
 * api.js — Single entry point gọi backend API.
 * Phase 6: snapshot endpoints + multi-tenant header.
 */

const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api/v1";


// ─────────────────────────────────────────────────────────────
// Project context (multi-tenant)
// ─────────────────────────────────────────────────────────────

const PROJECT_KEY = "lora_project_id";

export function getProjectId() {
  try { return localStorage.getItem(PROJECT_KEY) || null; }
  catch { return null; }
}

export function setProjectId(id) {
  try {
    if (id) localStorage.setItem(PROJECT_KEY, id);
    else    localStorage.removeItem(PROJECT_KEY);
  } catch { /* ignore */ }
}


// ─────────────────────────────────────────────────────────────
// ML model cache (per campaign + algorithm)
// Key: ml_model:{campaignId}:{algo}
// ─────────────────────────────────────────────────────────────

const ML_MODEL_KEY_PREFIX = "ml_model";

function mlModelKey(campaignId, algo) {
  return `${ML_MODEL_KEY_PREFIX}:${campaignId}:${algo}`;
}

export function getCachedModelId(campaignId, algo) {
  try { return localStorage.getItem(mlModelKey(campaignId, algo)) || null; }
  catch { return null; }
}

export function setCachedModelId(campaignId, algo, modelId) {
  try {
    if (modelId) localStorage.setItem(mlModelKey(campaignId, algo), modelId);
    else         localStorage.removeItem(mlModelKey(campaignId, algo));
  } catch { /* ignore */ }
}

export function clearCachedModelId(campaignId, algo) {
  try { localStorage.removeItem(mlModelKey(campaignId, algo)); }
  catch { /* ignore */ }
}

function authHeaders() {
  const pid = getProjectId();
  return pid ? { "X-Project-Id": pid } : {};
}


// ─────────────────────────────────────────────────────────────
// Core request
// ─────────────────────────────────────────────────────────────

async function request(path, options = {}) {
  const url     = `${BASE}${path}`;
  const headers = { ...authHeaders(), ...(options.headers || {}) };

  let res;
  try {
    res = await fetch(url, { ...options, headers });
  } catch (e) {
    throw new Error(`Network error: ${e.message}`);
  }

  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(`HTTP ${res.status}: non-JSON response`);
  }

  const json = await res.json();

  if (json && typeof json === "object" && "success" in json) {
    if (!json.success) {
      const err = new Error(json.error?.message || `HTTP ${res.status}`);
      err.code    = json.error?.code;
      err.details = json.error?.details;
      err.status  = res.status;
      throw err;
    }
    return json.data;
  }

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return json;
}

async function requestRaw(path, options = {}) {
  const headers = { ...authHeaders(), ...(options.headers || {}) };
  const res  = await fetch(`${BASE}${path}`, { ...options, headers });
  const json = await res.json();
  if (json && typeof json === "object" && "success" in json && !json.success) {
    const err = new Error(json.error?.message || `HTTP ${res.status}`);
    err.code = json.error?.code;
    throw err;
  }
  return json;
}

function buildQuery(params = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") q.append(k, v);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const apiUrl = (path) => `${BASE}${path}`;


export const api = {
  // ── Campaigns / Gateways / Measurements ─────────────────────
  getCampaigns: () => request("/campaigns/"),
  getGateways:  () => request("/gateways/"),

  getMeasurements: (campaignId, gatewayId = null, limit = 500, page = 1) => {
    const qs = buildQuery({ campaignId, gatewayId, limit, page });
    return request(`/measurements/${qs}`);
  },
  getStats: (campaignId) =>
    request(`/measurements/stats${buildQuery({ campaignId })}`),

  // ── Gateway Health (P2) ────────────────────────────────────
  getGatewayHealth: (projectId = null) =>
    requestRaw(`/gateway-health/${buildQuery({ projectId })}`),

  // ── Coverage (P5) ──────────────────────────────────────────
  getCoverageCheck: (lat, lng, radiusM = 300) =>
    request(`/coverage/check${buildQuery({ lat, lng, radiusM })}`),

  getCoverageSuggestMove: (lat, lng, searchRadiusM = 500) =>
    request(`/coverage/suggest-move${buildQuery({ lat, lng, searchRadiusM })}`),

  getCoveragePathToCoverage: (lat, lng, opts = {}) =>
    request(`/coverage/path-to-coverage${buildQuery({
      lat, lng,
      maxSteps:      opts.maxSteps,
      stepM:         opts.stepM,
      searchRadiusM: opts.searchRadiusM,
    })}`),

  // ── Simulator / Optimizer (P1) ─────────────────────────────
  simulateCoverage: (transmitters, bbox, gridResolutionM = 50, environment = "urban", frequencyMhz = 923.0, opts = {}) =>
    request("/simulator/coverage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transmitters, bbox, gridResolutionM, environment, frequencyMhz,
        ...(opts.useCalibration  ? { useCalibration: true } : {}),
        ...(opts.spreadingFactor ? { spreadingFactor: opts.spreadingFactor } : {}),
      }),
    }),

  // ── Sandbox (P6) ───────────────────────────────────────────
  sandboxPredictPoint: (body) =>
    request("/sandbox/predict-point", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  sandboxRadialProfile: (body) =>
    request("/sandbox/radial-profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ── Exports (P7 + P1) ──────────────────────────────────────
  exportGeoJSONUrl: (campaignId) => apiUrl(`/exports/${campaignId}/measurements.geojson`),
  exportKMLUrl:     (campaignId) => apiUrl(`/exports/${campaignId}/measurements.kml`),
  exportBoQUrl:     (campaignId) => apiUrl(`/exports/${campaignId}/boq.xlsx`),

  // ── Calibration (P2) ───────────────────────────────────────
  uploadCalibrationCsv: (campaignId, file) => {
    const fd = new FormData();
    fd.append("file", file);
    return request(`/calibration/${campaignId}/upload`, {
      method: "POST",
      body:   fd,
    });
  },
  getCalibrationMetrics: (campaignId) =>
    request(`/calibration/${campaignId}/metrics`),

  // ── Reports / Scenarios (P3 / P4) ──────────────────────────
  reportPdfUrl: (campaignId) => apiUrl(`/reports/${campaignId}.pdf`),

  compareScenarios: (campaignIdA, campaignIdB) =>
    request("/scenarios/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ campaignIdA, campaignIdB }),
    }),

  // ── Snapshots (Phase 6 — version history) ──────────────────
  listSnapshots:    (campaignId) => request(`/snapshots/${campaignId}`),
  getSnapshotGrid:  (snapshotId) => request(`/snapshots/${snapshotId}/grid`),
  restoreSnapshot:  (snapshotId) =>
    request(`/snapshots/${snapshotId}/restore`, { method: "POST" }),
  deleteSnapshot:   (snapshotId) =>
    request(`/snapshots/${snapshotId}`, { method: "DELETE" }),

  // ── Webhook Subscriptions (P2 / P4) ────────────────────────
  listWebhookSubs: () => request("/webhook-subscriptions/"),
  createWebhookSub: (projectId, name, targetUrl, eventTypes = []) =>
    request("/webhook-subscriptions/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, name, targetUrl, eventTypes }),
    }),
  deleteWebhookSub: (id) =>
    request(`/webhook-subscriptions/${id}`, { method: "DELETE" }),
  testFireWebhook: (id) =>
    request(`/webhook-subscriptions/${id}/test`, { method: "POST" }),
  listWebhookDeliveries: (id) =>
    request(`/webhook-subscriptions/${id}/deliveries`),

  // ── Predict ─────────────────────────────────────────────────
  getPredictionGrid:   (campaignId) => request(`/predict/grid/${campaignId}`),
  getPredictionStatus: (campaignId) => request(`/predict/status/${campaignId}`),

  runInterpolation: (campaignId, algorithm = "idw", gridResolutionM = 50, mlModelId = null) =>
    request(`/predict/run/${campaignId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ algorithm, gridResolutionM, minMeasurements: 10, mlModelId }),
    }),

  trainModel: (campaignId, algorithm = "xgboost", hyperparameters = null) =>
    request(`/predict/train/${campaignId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ algorithm, hyperparameters, minMeasurements: 30, nCvSplits: 5 }),
    }),

  listModels:  () => request("/predict/models"),
  deleteModel: (modelId) =>
    request(`/predict/models/${modelId}`, { method: "DELETE" }),

  getAois: () => request("/aois"),
 
  getAoi:  (slug) => request(`/aois/${slug}`),
 
  getAoiCandidates: (slug, source = null) =>
    request(`/aois/${slug}/candidates${buildQuery({ source })}`),
 
  createOptimizationRun: (payload) =>
    request("/optimization-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
 
  listOptimizationRuns: (slug, opts = {}) =>
    request(`/aois/${slug}/optimization-runs${buildQuery({
      page: opts.page, limit: opts.limit, mode: opts.mode,
    })}`),
 
  getOptimizationRun: (runId) =>
    request(`/optimization-runs/${runId}`),
 
  deleteOptimizationRun: (runId) =>
    request(`/optimization-runs/${runId}`, { method: "DELETE" }),
};