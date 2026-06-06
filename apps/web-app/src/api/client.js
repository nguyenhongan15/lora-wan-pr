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
  // tx_power_dbm capped 14 dBm theo AS923-2 regional params (BE validate cùng range).
  tx_power_dbm: z.number().min(-10).max(14).optional(),
  // environment: outdoor | indoor (mặc định trong nhà) | indoor_deep (sâu trong nhà,
  // ít cửa sổ). Thiếu = outdoor (default ở BE).
  environment: z.enum(["outdoor", "indoor", "indoor_deep"]).optional(),
});

export const Confidence = z.object({
  score: z.number().min(0).max(1),
  method: z.enum(["physics", "empirical", "residual", "ensemble", "bayesian"]),
  // σ² components (dB²). Tổng σ = √(epi+ale) là sai số 1σ ~68% CI Gaussian.
  // Default 0 để gracefully degrade với BE chưa rebuild.
  epistemic_variance_db2: z.number().nonnegative().default(0),
  aleatoric_variance_db2: z.number().nonnegative().default(0),
});

export const LinkBudget = z.object({
  rssi_dbm: z.number(),
  snr_db: z.number(),
  margin_db: z.number(),
  status: z.enum(["strong", "marginal", "weak", "no_coverage"]),
});

export const Prediction = z.object({
  // rssi_dbm/snr_db giữ nghĩa = downlink (backward compat); coverage_status =
  // worst-of(uplink, downlink). Field uplink/downlink/bottleneck là optional
  // để gracefully degrade với BE chưa rebuild.
  rssi_dbm: z.number(),
  snr_db: z.number(),
  coverage_status: z.enum(["strong", "marginal", "weak", "no_coverage"]),
  serving_gateway_id: z.string().uuid().nullable(),
  confidence: Confidence,
  model_version: z.string(),
  recommended_sf: z.number().int().min(7).max(12),
  uplink: LinkBudget.optional(),
  downlink: LinkBudget.optional(),
  bottleneck: z.enum(["uplink", "downlink", "both_ok"]).optional(),
  // Path loss tổng (basic transmission + BEL nếu có); UL/DL đối xứng. Default 0
  // để graceful degrade với BE chưa rebuild.
  path_loss_db: z.number().default(0),
  // Khoảng cách target → serving gateway (km). Serving GW chọn theo
  // min(UL_margin, DL_margin) = "gateway tín hiệu mạnh nhất" — không phải nearest.
  distance_to_serving_gateway_km: z.number().nonnegative().default(0),
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
 * @typedef {z.infer<typeof LinkBudget>} LinkBudgetT
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
 * GET /api/v1/gateways — backend resolver dùng chung edge/filters.py.
 *   contributor=community (default): tất cả gateway public.
 *   contributor=me / user/<uuid>: chỉ gateway từng phục vụ survey của user
 *     đó (JOIN serving_gateway_id). Cần Bearer token cho mode != community.
 *
 * @param {BBox=} bbox
 * @param {{
 *   contributor?: ContributorMode,
 *   linkedSourceId?: string,
 * }=} opts
 * @returns {Promise<z.infer<typeof GatewayList>>}
 */
export async function listGateways(bbox, opts) {
  const url = new URL(`${API_BASE_URL}/api/v1/gateways`);
  if (bbox) {
    url.searchParams.set("min_lon", String(bbox.min_lon));
    url.searchParams.set("min_lat", String(bbox.min_lat));
    url.searchParams.set("max_lon", String(bbox.max_lon));
    url.searchParams.set("max_lat", String(bbox.max_lat));
  }
  const contributor = opts?.contributor ?? "community";
  if (contributor !== "community") {
    url.searchParams.set("contributor", contributor);
  }
  if (opts?.linkedSourceId) url.searchParams.set("linked_source", opts.linkedSourceId);

  const doFetch = contributor === "community" ? fetch : authFetch;
  const res = await doFetch(url);
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
  device_id: z.string().nullable(),
  frequency_mhz: z.number(),
  timestamp: z.string(),
  code_rate: z.string().nullable(),
});

export const SurveyTrainingList = z.object({
  items: z.array(SurveyTrainingPoint),
  total: z.number().int(),
});

/**
 * @typedef {z.infer<typeof SurveyTrainingPoint>} SurveyTrainingPointT
 */

export const MyDeviceItem = z.object({
  device_id: z.string(),
  count: z.number().int().nonnegative(),
});

export const MyDeviceList = z.object({
  items: z.array(MyDeviceItem),
});

/**
 * @typedef {z.infer<typeof MyDeviceItem>} MyDeviceItemT
 */

// ── Coverage lookup theo địa chỉ (F2) ─────────────────────────────────────

export const ResolvedAddress = z.object({
  latitude: z.number(),
  longitude: z.number(),
  display_name: z.string(),
  provider: z.enum(["cache", "nominatim", "vietmap", "goong", "google"]),
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
 * @param {AbortSignal} [signal] huỷ giữa chừng (user resubmit / reset)
 * @returns {Promise<CoverageBatchResponseT>}
 */
export async function lookupCoverageBatch(req, signal) {
  const parsed = CoverageBatchRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/coverage/batch`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
    signal,
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
 * @typedef {"timestamp" | "rssi" | "snr"} SortBy
 * @typedef {"asc" | "desc"} SortOrder
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
 *   source?: string,
 *   sfList?: ReadonlyArray<number>,
 *   rssiMin?: number,
 *   rssiMax?: number,
 *   snrMin?: number,
 *   snrMax?: number,
 *   timeFrom?: string,
 *   timeTo?: string,
 *   since?: string,
 *   sortBy?: SortBy,
 *   sortOrder?: SortOrder,
 *   rankFrom?: number,
 *   rankTo?: number,
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

  if (opts?.sfList && opts.sfList.length > 0) {
    url.searchParams.set("sf", opts.sfList.join(","));
  }
  if (opts?.rssiMin != null) url.searchParams.set("rssi_min", String(opts.rssiMin));
  if (opts?.rssiMax != null) url.searchParams.set("rssi_max", String(opts.rssiMax));
  if (opts?.snrMin != null) url.searchParams.set("snr_min", String(opts.snrMin));
  if (opts?.snrMax != null) url.searchParams.set("snr_max", String(opts.snrMax));
  if (opts?.timeFrom) url.searchParams.set("time_from", opts.timeFrom);
  if (opts?.timeTo) url.searchParams.set("time_to", opts.timeTo);
  if (opts?.since) url.searchParams.set("since", opts.since);
  if (opts?.sortBy && opts.sortBy !== "timestamp") {
    url.searchParams.set("sort_by", opts.sortBy);
  }
  if (opts?.sortOrder && opts.sortOrder !== "desc") {
    url.searchParams.set("sort_order", opts.sortOrder);
  }
  if (opts?.rankFrom != null) url.searchParams.set("rank_from", String(opts.rankFrom));
  if (opts?.rankTo != null) url.searchParams.set("rank_to", String(opts.rankTo));

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

/**
 * GET /api/v1/survey/me/devices — list distinct device_ids của user, kèm
 * số điểm. Dùng cho dropdown filter "Bản đồ của tôi". Cần token (authFetch).
 *
 * @param {{ linkedSourceId?: string }=} opts
 * @returns {Promise<z.infer<typeof MyDeviceList>>}
 */
export async function listMyDevices(opts) {
  const url = new URL(`${API_BASE_URL}/api/v1/survey/me/devices`);
  if (opts?.linkedSourceId) url.searchParams.set("linked_source", opts.linkedSourceId);
  const res = await authFetch(url);
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({
      type: "about:blank",
      title: "Failed to list devices",
      status: res.status,
    });
  }
  return MyDeviceList.parse(await res.json());
}

// ── CSV upload survey (plan community-data-contribution) ──────────────────

export const CsvUploadResponse = z.object({
  parsed_count: z.number().int().nonnegative(),
  parse_rejected_count: z.number().int().nonnegative(),
  parse_rejected_reasons: z.array(z.string()).default([]),
  inserted_count: z.number().int().nonnegative(),
  promoted_count: z.number().int().nonnegative(),
  promote_rejected_count: z.number().int().nonnegative(),
  promote_rejected_by_reason: z.record(z.string(), z.number().int().nonnegative()).default({}),
});

/** @typedef {z.infer<typeof CsvUploadResponse>} CsvUploadResponseT */

/**
 * POST /api/v1/me/uploads/csv — multipart upload of survey measurements.
 *
 * `submitToCommunity=false` (default) → CSV chỉ ở quarantine, chỉ chính user
 * xem trong dashboard "Bản đồ của tôi". `true` → mỗi row chạy qua
 * TrustValidator (L1 bbox + gateway, L2 ITU physics, L3 reputation); pass →
 * vào ts.survey_training public dataset.
 *
 * @param {File} file
 * @param {boolean} submitToCommunity
 * @returns {Promise<CsvUploadResponseT>}
 */
export async function uploadMeasurementsCsv(file, submitToCommunity) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("submit_to_community", submitToCommunity ? "true" : "false");
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/uploads/csv`, {
    method: "POST",
    body: fd,
    // KHÔNG set content-type: browser tự thêm boundary cho multipart/form-data.
  });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({
      type: "about:blank",
      title: "Failed to upload CSV",
      status: res.status,
    });
  }
  return CsvUploadResponse.parse(await res.json());
}

export const CsvUploadStats = z.object({
  total: z.number().int().nonnegative(),
  pending: z.number().int().nonnegative(),
  pending_review: z.number().int().nonnegative(),
  promoted: z.number().int().nonnegative(),
  rejected: z.number().int().nonnegative(),
});

/** @typedef {z.infer<typeof CsvUploadStats>} CsvUploadStatsT */

/**
 * GET /api/v1/me/uploads/csv/stats — tổng quan CSV của user. Dùng cho card
 * "Tải lên CSV của tôi" ở trang Nguồn dữ liệu để hiển thị backlog pending.
 *
 * @returns {Promise<CsvUploadStatsT>}
 */
export async function fetchCsvUploadStats() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/uploads/csv/stats`);
  if (!res.ok) {
    throw new ApiError({
      type: "about:blank",
      title: "Failed to load CSV stats",
      status: res.status,
    });
  }
  return CsvUploadStats.parse(await res.json());
}

export const CsvUploadBatch = z.object({
  uploaded_at: z.string(),
  total: z.number().int().nonnegative(),
  pending: z.number().int().nonnegative(),
  pending_review: z.number().int().nonnegative(),
  promoted: z.number().int().nonnegative(),
  rejected: z.number().int().nonnegative(),
});

export const CsvUploadBatchList = z.object({
  items: z.array(CsvUploadBatch).default([]),
});

/** @typedef {z.infer<typeof CsvUploadBatch>} CsvUploadBatchT */

/**
 * GET /api/v1/me/uploads/csv/batches — list các lần upload (group uploaded_at).
 *
 * @returns {Promise<CsvUploadBatchT[]>}
 */
export async function listCsvUploadBatches() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/uploads/csv/batches`);
  if (!res.ok) {
    throw new ApiError({
      type: "about:blank",
      title: "Failed to list CSV batches",
      status: res.status,
    });
  }
  const parsed = CsvUploadBatchList.parse(await res.json());
  return parsed.items;
}

/**
 * DELETE /api/v1/me/uploads/csv/batches?uploaded_at=ISO — xoá 1 batch.
 *
 * @param {string} uploadedAt ISO 8601 trả về từ list endpoint (truyền nguyên).
 */
export async function deleteCsvUploadBatch(uploadedAt) {
  const url = new URL(`${API_BASE_URL}/api/v1/me/uploads/csv/batches`);
  url.searchParams.set("uploaded_at", uploadedAt);
  const res = await authFetch(url.toString(), { method: "DELETE" });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({
      type: "about:blank",
      title: "Failed to delete CSV batch",
      status: res.status,
    });
  }
  return await res.json();
}

export const CsvPromoteResponse = z.object({
  promoted_count: z.number().int().nonnegative(),
  promote_rejected_count: z.number().int().nonnegative(),
  promote_rejected_by_reason: z.record(z.string(), z.number().int().nonnegative()).default({}),
});

/** @typedef {z.infer<typeof CsvPromoteResponse>} CsvPromoteResponseT */

/**
 * POST /api/v1/me/uploads/csv/batches/promote?uploaded_at=... — chạy
 * TrustValidator chỉ trên rows của 1 batch (1 file = 1 lần upload).
 *
 * @param {string} uploadedAt ISO 8601 (truyền nguyên từ list endpoint).
 * @returns {Promise<CsvPromoteResponseT>}
 */
export async function promoteCsvBatch(uploadedAt) {
  const url = new URL(`${API_BASE_URL}/api/v1/me/uploads/csv/batches/promote`);
  url.searchParams.set("uploaded_at", uploadedAt);
  const res = await authFetch(url.toString(), { method: "POST" });
  if (!res.ok) {
    const ct = res.headers.get("content-type") ?? "";
    if (ct.includes("application/problem+json") || ct.includes("application/json")) {
      throw new ApiError(ProblemDetails.parse(await res.json()));
    }
    throw new ApiError({
      type: "about:blank",
      title: "Failed to promote CSV batch",
      status: res.status,
    });
  }
  return CsvPromoteResponse.parse(await res.json());
}
