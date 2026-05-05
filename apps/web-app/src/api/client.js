// @ts-check
import { z } from "zod";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export const PredictRequest = z.object({
  latitude: z.number().min(-90).max(90),
  longitude: z.number().min(-180).max(180),
  spreading_factor: z.number().int().min(7).max(12),
  frequency_mhz: z.number().default(868),
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

/**
 * GET /api/v1/survey/training
 * @param {BBox=} bbox
 * @returns {Promise<z.infer<typeof SurveyTrainingList>>}
 */
export async function listSurveyTraining(bbox) {
  const url = new URL(`${API_BASE_URL}/api/v1/survey/training`);
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
      title: "Failed to list survey points",
      status: res.status,
    });
  }
  return SurveyTrainingList.parse(await res.json());
}
