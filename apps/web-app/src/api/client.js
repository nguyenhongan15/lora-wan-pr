// @ts-check
import { z } from "zod";
import { authFetch } from "../auth/_intercept.js";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const PredictRequest = z.object({
  latitude: z.number().min(-90).max(90),
  longitude: z.number().min(-180).max(180),
  spreading_factor: z.number().int().min(7).max(12),
  frequency_mhz: z.number().default(923),
});

export const Confidence = z.object({
  score: z.number().min(0).max(1),
  method: z.enum(["empirical", "residual", "ensemble", "bayesian"]),
});

export const Prediction = z.object({
  rssi_dbm: z.number(),
  snr_db: z.number(),
  coverage_status: z.enum(["strong", "marginal", "weak", "no_coverage"]),
  serving_gateway_id: z.string().uuid().nullable(),
  confidence: Confidence,
  model_version: z.string(),
  recommended_sf: z.number().int().min(7).max(12),
});

export const ProblemDetails = z.object({
  type: z.string(),
  title: z.string(),
  status: z.number(),
  detail: z.string().optional(),
  instance: z.string().optional(),
  code: z.string().optional(),
  traceId: z.string().optional(),
});

/**
 * @typedef {z.infer<typeof PredictRequest>} PredictRequestT
 * @typedef {z.infer<typeof Prediction>} PredictionT
 * @typedef {z.infer<typeof ProblemDetails>} ProblemDetailsT
 */

export class ApiError extends Error {
  /** @param {ProblemDetailsT} problem */
  constructor(problem) {
    super(`${problem.title} (${problem.status})`);
    this.name = "ApiError";
    /** @type {ProblemDetailsT} */
    this.problem = problem;
  }
}

/**
 * POST /api/v1/coverage/predict
 * @param {PredictRequestT} req
 * @returns {Promise<PredictionT>}
 */
export async function predictCoverage(req) {
  const parsed = PredictRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/coverage/predict`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });

  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (
      ct.includes("application/problem+json") ||
      ct.includes("application/json")
    ) {
      const body = await res.json();
      throw new ApiError(ProblemDetails.parse(body));
    }
    throw new ApiError({
      type: "about:blank",
      title: "HTTP error",
      status: res.status,
    });
  }

  return Prediction.parse(await res.json());
}

// ── Gateway directory ─────────────────────────────────────────────────────

export const Gateway = z.object({
  id: z.string().uuid(),
  code: z.string(),
  name: z.string(),
  latitude: z.number(),
  longitude: z.number(),
  altitude_m: z.number(),
  antenna_height_m: z.number(),
  antenna_gain_dbi: z.number(),
  tx_power_dbm: z.number(),
  frequency_mhz: z.number(),
});

export const GatewayList = z.object({
  items: z.array(Gateway),
  total: z.number().int(),
});

/**
 * @typedef {z.infer<typeof Gateway>} GatewayT
 * @typedef {{ min_lon: number, min_lat: number, max_lon: number, max_lat: number }} BBox
 */

/**
 * GET /api/v1/gateways
 * @param {BBox=} bbox
 * @returns {Promise<z.infer<typeof GatewayList>>}
 */
export async function listGateways(bbox) {
  const url = new URL(`${API_BASE_URL}/api/v1/gateways`);
  if (bbox) {
    url.searchParams.set("min_lon", String(bbox.min_lon));
    url.searchParams.set("min_lat", String(bbox.min_lat));
    url.searchParams.set("max_lon", String(bbox.max_lon));
    url.searchParams.set("max_lat", String(bbox.max_lat));
  }
  const res = await fetch(url);
  if (!res.ok) {
    throw new ApiError({
      type: "about:blank",
      title: "Failed to list gateways",
      status: res.status,
    });
  }
  return GatewayList.parse(await res.json());
}

// ── Gateway admin CRUD ────────────────────────────────────────────────────

export const GatewayCreateRequest = z.object({
  code: z.string().min(3).max(64),
  name: z.string().min(1).max(255),
  latitude: z.number().min(-90).max(90),
  longitude: z.number().min(-180).max(180),
  altitude_m: z.number().default(0),
  antenna_height_m: z.number().min(0).default(10),
  antenna_gain_dbi: z.number().default(2),
  tx_power_dbm: z.number().min(-10).max(30).default(14),
  frequency_mhz: z.union([z.literal(433), z.literal(868), z.literal(915), z.literal(923)]).default(868),
});

export const GatewayPatchRequest = z.object({
  name: z.string().min(1).max(255).optional(),
  altitude_m: z.number().optional(),
  antenna_height_m: z.number().min(0).optional(),
  antenna_gain_dbi: z.number().optional(),
  tx_power_dbm: z.number().min(-10).max(30).optional(),
});

/**
 * @typedef {z.infer<typeof GatewayCreateRequest>} GatewayCreateRequestT
 * @typedef {z.infer<typeof GatewayPatchRequest>} GatewayPatchRequestT
 */

/**
 * GET /api/v1/gateways/{id} — returns body + ETag header.
 * @param {string} id
 * @returns {Promise<{ gateway: GatewayT, etag: string | null }>}
 */
export async function getGateway(id) {
  const res = await fetch(`${API_BASE_URL}/api/v1/gateways/${id}`);
  if (!res.ok) {
    throw new ApiError({
      type: "about:blank",
      title: "Failed to load gateway",
      status: res.status,
    });
  }
  const body = Gateway.parse(await res.json());
  return { gateway: body, etag: res.headers.get("etag") };
}

/**
 * POST /api/v1/gateways
 * @param {GatewayCreateRequestT} req
 * @returns {Promise<GatewayT>}
 */
export async function createGateway(req) {
  const parsed = GatewayCreateRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/gateways`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({ type: "about:blank", title: "Create failed", status: res.status });
  }
  return Gateway.parse(await res.json());
}

/**
 * PATCH /api/v1/gateways/{id} with If-Match.
 * @param {string} id
 * @param {string} etag
 * @param {GatewayPatchRequestT} patch
 * @returns {Promise<{ gateway: GatewayT, etag: string | null }>}
 */
export async function patchGateway(id, etag, patch) {
  const parsed = GatewayPatchRequest.parse(patch);
  const res = await fetch(`${API_BASE_URL}/api/v1/gateways/${id}`, {
    method: "PATCH",
    headers: {
      "content-type": "application/json",
      "if-match": etag,
    },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({ type: "about:blank", title: "Patch failed", status: res.status });
  }
  const body = Gateway.parse(await res.json());
  return { gateway: body, etag: res.headers.get("etag") };
}

// ── Survey training points (read-only) ────────────────────────────────────

export const SurveyTrainingPoint = z.object({
  latitude: z.number(),
  longitude: z.number(),
  rssi_dbm: z.number(),
  snr_db: z.number(),
  spreading_factor: z.number().int(),
  serving_gateway_id: z.string().uuid().nullable(),
});

export const SurveyTrainingList = z.object({
  items: z.array(SurveyTrainingPoint),
  total: z.number().int(),
});

/**
 * @typedef {z.infer<typeof SurveyTrainingPoint>} SurveyTrainingPointT
 */

// ── Coverage lookup theo địa chỉ (F2) ─────────────────────────────────────

export const ResolvedAddress = z.object({
  latitude: z.number(),
  longitude: z.number(),
  display_name: z.string(),
  provider: z.enum(["postgres", "nominatim", "vietmap", "goong", "google"]),
  confidence: z.number().min(0).max(1),
});

export const CoverageLookupResponse = z.object({
  address: ResolvedAddress,
  prediction: Prediction,
});

export const CoverageLookupRequest = z.object({
  address: z.string().min(1).max(500),
  spreading_factor: z.number().int().min(7).max(12).default(7),
  frequency_mhz: z.number().default(923),
});

/**
 * @typedef {z.infer<typeof CoverageLookupResponse>} CoverageLookupResponseT
 * @typedef {z.infer<typeof CoverageLookupRequest>} CoverageLookupRequestT
 */

/**
 * POST /api/v1/coverage/lookup
 * @param {CoverageLookupRequestT} req
 * @returns {Promise<CoverageLookupResponseT>}
 */
export async function lookupCoverageByAddress(req) {
  const parsed = CoverageLookupRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/coverage/lookup`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (
      ct.includes("application/problem+json") ||
      ct.includes("application/json")
    ) {
      const body = await res.json();
      throw new ApiError(ProblemDetails.parse(body));
    }
    throw new ApiError({
      type: "about:blank",
      title: "HTTP error",
      status: res.status,
    });
  }
  return CoverageLookupResponse.parse(await res.json());
}

// ── Coverage batch (bulk lookup) ──────────────────────────────────────────

export const CoverageBatchItem = z.object({
  label: z.string().max(200).optional(),
  address: z.string().min(1).max(500).optional(),
  latitude: z.number().min(-90).max(90).optional(),
  longitude: z.number().min(-180).max(180).optional(),
});

export const CoverageBatchRequest = z.object({
  items: z.array(CoverageBatchItem).min(1).max(500),
  spreading_factor: z.number().int().min(7).max(12).default(7),
  frequency_mhz: z.number().default(923),
});

export const CoverageBatchItemResult = z.object({
  label: z.string().nullable(),
  status: z.enum(["ok", "error"]),
  address: ResolvedAddress.nullable().optional(),
  prediction: Prediction.nullable().optional(),
  error_code: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
});

export const CoverageBatchResponse = z.object({
  items: z.array(CoverageBatchItemResult),
  ok_count: z.number().int(),
  error_count: z.number().int(),
});

/**
 * @typedef {z.infer<typeof CoverageBatchRequest>} CoverageBatchRequestT
 * @typedef {z.infer<typeof CoverageBatchResponse>} CoverageBatchResponseT
 * @typedef {z.infer<typeof CoverageBatchItemResult>} CoverageBatchItemResultT
 */

/**
 * POST /api/v1/coverage/batch
 * @param {CoverageBatchRequestT} req
 * @returns {Promise<CoverageBatchResponseT>}
 */
export async function lookupCoverageBatch(req) {
  const parsed = CoverageBatchRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/coverage/batch`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (
      ct.includes("application/problem+json") ||
      ct.includes("application/json")
    ) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({
      type: "about:blank",
      title: "Batch lookup failed",
      status: res.status,
    });
  }
  return CoverageBatchResponse.parse(await res.json());
}

/**
 * @typedef {"community" | "me" | `user/${string}`} ContributorMode
 *
 * GET /api/v1/survey/training — backend resolver: edge/filters.py.
 *   contributor=community (default): public map; backend filter
 *     contribute_to_community=true + status='active' + uploader chưa disable.
 *   contributor=me: cần token; sub-filter qua linkedSourceId.
 *   contributor=user/<uuid>: admin only.
 *
 * Community gọi raw fetch (không gửi Authorization để tránh 401 spurious khi
 * token đã expire). Mode khác qua authFetch để attach Bearer + clear store
 * trên 401.
 *
 * @param {BBox=} bbox
 * @param {{
 *   deviceId?: string,
 *   limit?: number,
 *   contributor?: ContributorMode,
 *   linkedSourceId?: string,
 *   source?: string
 * }=} opts
 * @returns {Promise<z.infer<typeof SurveyTrainingList>>}
 */
export async function listSurveyTraining(bbox, opts) {
  const url = new URL(`${API_BASE_URL}/api/v1/survey/training`);
  if (bbox) {
    url.searchParams.set("min_lon", String(bbox.min_lon));
    url.searchParams.set("min_lat", String(bbox.min_lat));
    url.searchParams.set("max_lon", String(bbox.max_lon));
    url.searchParams.set("max_lat", String(bbox.max_lat));
  }
  if (opts?.deviceId) url.searchParams.set("device_id", opts.deviceId);
  if (opts?.limit) url.searchParams.set("limit", String(opts.limit));

  const contributor = opts?.contributor ?? "community";
  if (contributor !== "community") {
    url.searchParams.set("contributor", contributor);
  }
  if (opts?.linkedSourceId) url.searchParams.set("linked_source", opts.linkedSourceId);
  if (opts?.source) url.searchParams.set("source", opts.source);

  const doFetch = contributor === "community" ? fetch : authFetch;
  const res = await doFetch(url);
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({
      type: "about:blank",
      title: "Failed to list survey points",
      status: res.status,
    });
  }
  return SurveyTrainingList.parse(await res.json());
}
