// @ts-check
// Sources API client — me/sources CRUD + manual sync + upload batches.
//
// Mirror Pydantic schemas (services/api-service/.../edge/schemas.py
// "Linking — me/sources" + "Sync" + "Upload batches"). Zod ↔ Pydantic
// duplicate cố ý: plan-auth §11 step 9 quyết định KHÔNG codegen — đổi shape
// sửa cả 2, CI integration test catch lệch.
//
// Tất cả endpoint cần Bearer → authFetch (auth/_intercept.js). authFetch tự
// clear store khi 401 → UI fall back về Login modal.
//
// ApiError + ProblemDetails reuse từ auth/client.js (1 lớp lỗi xuyên app).

import { z } from "zod";
import { ApiError, ProblemDetails } from "../auth/client.js";
import { authFetch } from "../auth/_intercept.js";

// Xem ghi chú ở api/client.js: localhost → 8000 cho dev, ngược lại theo env.
const API_BASE_URL = (() => {
  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
  }
  return import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
})();

// ── Schemas: linked sources ───────────────────────────────────────────────

export const LinkedSource = z.object({
  id: z.string().uuid(),
  source_type: z.string(),
  label: z.string(),
  status: z.enum(["active", "paused", "failed"]),
  last_sync_at: z.string().nullable(),
  last_sync_error: z.string().nullable(),
  created_at: z.string(),
  // Webhook presence-only (plan ChirpStack per-user webhook ingest §1). Token
  // plaintext CHỈ xuất hiện trong LinkSourceCreated / WebhookSecret response.
  has_webhook_token: z.boolean().default(false),
  webhook_rotated_at: z.string().nullable().default(null),
});

export const LinkedSourceList = z.object({
  items: z.array(LinkedSource),
  total: z.number().int().nonnegative(),
});

// POST /me/sources response — `webhook_url` + `webhook_token` chỉ có khi
// vừa link source thuộc whitelist (chirpstack). Source khác → cả 2 = null.
export const LinkSourceCreated = z.object({
  source: LinkedSource,
  webhook_url: z.string().nullable(),
  webhook_token: z.string().nullable(),
});

// POST /me/sources/{id}/rotate-webhook response — luôn có plaintext token mới.
export const WebhookSecret = z.object({
  source: LinkedSource,
  webhook_url: z.string(),
  webhook_token: z.string(),
});

export const Device = z.object({
  id: z.string().uuid(),
  dev_eui: z.string(),
  name: z.string().nullable(),
  source_type: z.string(),
  last_seen_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const DeviceList = z.object({
  items: z.array(Device),
  total: z.number().int().nonnegative(),
});

export const LinkSourceRequest = z.object({
  source_type: z.string().min(1).max(64),
  label: z.string().min(1).max(100),
  // Adapter-specific. Lpwanmapper: { email, password }. Backend tự test()
  // qua adapter.connect — sai → 400 credential_test_failed.
  credentials: z.record(z.string(), z.string()).refine(
    (obj) => Object.keys(obj).length >= 1,
    { message: "credentials không được rỗng" },
  ),
});

export const LinkedSourcePatchRequest = z.object({
  status: z.enum(["active", "paused"]),
});

export const SyncResult = z.object({
  linked_source_id: z.string().uuid(),
  gateways_inserted: z.number().int().nonnegative(),
  gateways_updated: z.number().int().nonnegative(),
  gateways_quarantined: z.number().int().nonnegative(),
  measurements_inserted: z.number().int().nonnegative(),
  measurements_updated: z.number().int().nonnegative(),
  devices_inserted: z.number().int().nonnegative(),
  devices_updated: z.number().int().nonnegative(),
  last_sync_at: z.string().nullable(),
  error: z.string().nullable(),
});

// ── Schemas: upload batches (mig 0024 + refactor 2026-06-11) ──────────────

export const UploadKind = z.enum([
  "csv",
  "json",
  "sync_lpwanmapper",
  "sync_chirpstack",
  "live_session",
]);
export const BatchStatus = z.enum([
  "private",
  "pending",
  "public",
  "rejected",
  "deleted",
]);

export const UploadBatchItem = z.object({
  id: z.string().uuid(),
  kind: UploadKind,
  filename: z.string(),
  linked_source_id: z.string().uuid().nullable(),
  uploaded_at: z.string(),
  points_count: z.number().int().nonnegative(),
  status: BatchStatus,
  deleted_at: z.string().nullable().default(null),
});

export const UploadBatchListResponse = z.object({
  items: z.array(UploadBatchItem).default([]),
});

export const UploadOverviewResponse = z.object({
  batches_total: z.number().int().nonnegative(),
  points_total: z.number().int().nonnegative(),
  public_batches: z.number().int().nonnegative(),
  pending_batches: z.number().int().nonnegative(),
  private_batches: z.number().int().nonnegative(),
});

export const UploadBatchSubmitResponse = z.object({
  batch_id: z.string().uuid(),
  queued: z.number().int().nonnegative(),
});

export const UploadBatchDeleteResponse = z.object({
  batch_id: z.string().uuid(),
  deleted: z.boolean(),
});

// CSV/JSON upload — refactor 2026-06-11: upload luôn private, không còn
// `submit_to_community`. `batch_id` null khi parsed_count=0 (file sai schema).
export const CsvUploadResponse = z.object({
  batch_id: z.string().uuid().nullable(),
  parsed_count: z.number().int().nonnegative(),
  parse_rejected_count: z.number().int().nonnegative(),
  parse_rejected_reasons: z.array(z.string()).default([]),
  inserted_count: z.number().int().nonnegative(),
});

/**
 * @typedef {z.infer<typeof LinkedSource>} LinkedSourceT
 * @typedef {z.infer<typeof LinkedSourceList>} LinkedSourceListT
 * @typedef {z.infer<typeof LinkSourceRequest>} LinkSourceRequestT
 * @typedef {z.infer<typeof LinkSourceCreated>} LinkSourceCreatedT
 * @typedef {z.infer<typeof WebhookSecret>} WebhookSecretT
 * @typedef {z.infer<typeof Device>} DeviceT
 * @typedef {z.infer<typeof DeviceList>} DeviceListT
 * @typedef {z.infer<typeof LinkedSourcePatchRequest>} LinkedSourcePatchRequestT
 * @typedef {z.infer<typeof SyncResult>} SyncResultT
 * @typedef {z.infer<typeof UploadBatchItem>} UploadBatchItemT
 * @typedef {z.infer<typeof UploadOverviewResponse>} UploadOverviewResponseT
 * @typedef {z.infer<typeof UploadBatchSubmitResponse>} UploadBatchSubmitResponseT
 * @typedef {z.infer<typeof UploadBatchDeleteResponse>} UploadBatchDeleteResponseT
 * @typedef {z.infer<typeof CsvUploadResponse>} CsvUploadResponseT
 */

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * @param {Response} res
 * @returns {Promise<never>}
 */
async function _throwProblem(res) {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/problem+json") || ct.includes("application/json")) {
    const body = await res.json();
    throw new ApiError(ProblemDetails.parse(body));
  }
  throw new ApiError({
    type: "about:blank",
    title: "HTTP error",
    status: res.status,
  });
}

// ── Endpoints: linked sources ─────────────────────────────────────────────

/**
 * GET /api/v1/me/sources
 * @returns {Promise<LinkedSourceListT>}
 */
export async function listSources() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/sources`);
  if (!res.ok) await _throwProblem(res);
  return LinkedSourceList.parse(await res.json());
}

/**
 * POST /api/v1/me/sources — backend test() credential trước khi insert,
 * sai → 400 credential_test_failed (KHÔNG persist).
 *
 * Response chứa `webhook_url`/`webhook_token` plaintext 1 lần khi source
 * thuộc whitelist (chirpstack). Caller phải hiển thị + cảnh báo "copy ngay,
 * sau không xem lại được" — backend KHÔNG bao giờ trả token lần 2 (phải
 * rotate). Source khác (lpwanmapper): cả 2 = null.
 *
 * @param {LinkSourceRequestT} req
 * @returns {Promise<LinkSourceCreatedT>}
 */
export async function linkSource(req) {
  const parsed = LinkSourceRequest.parse(req);
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/sources`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);
  return LinkSourceCreated.parse(await res.json());
}

/**
 * POST /api/v1/me/sources/{id}/rotate-webhook — sinh token mới, invalidate
 * token cũ. Source không hỗ trợ webhook → 400.
 *
 * @param {string} id
 * @returns {Promise<WebhookSecretT>}
 */
export async function rotateWebhook(id) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/me/sources/${id}/rotate-webhook`,
    { method: "POST" },
  );
  if (!res.ok) await _throwProblem(res);
  return WebhookSecret.parse(await res.json());
}

/**
 * GET /api/v1/me/sources/{id}/devices — list devices đã sync.
 *
 * @param {string} id
 * @param {{ offset?: number, limit?: number }} [opts]
 * @returns {Promise<DeviceListT>}
 */
export async function listDevices(id, opts = {}) {
  const params = new URLSearchParams();
  if (opts.offset != null) params.set("offset", String(opts.offset));
  if (opts.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString();
  const url =
    `${API_BASE_URL}/api/v1/me/sources/${id}/devices` +
    (qs ? `?${qs}` : "");
  const res = await authFetch(url);
  if (!res.ok) await _throwProblem(res);
  return DeviceList.parse(await res.json());
}

/**
 * DELETE /api/v1/me/sources/{id} — 204 trên thành công.
 * Data đã đóng góp giữ lại với linked_source_id=NULL (migration 0007).
 * @param {string} id UUID
 */
export async function unlinkSource(id) {
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/sources/${id}`, {
    method: "DELETE",
  });
  if (!res.ok && res.status !== 204) await _throwProblem(res);
}

/**
 * PATCH /api/v1/me/sources/{id} — chỉ flip status (active/paused).
 * @param {string} id
 * @param {LinkedSourcePatchRequestT} patch
 * @returns {Promise<LinkedSourceT>}
 */
export async function patchSource(id, patch) {
  const parsed = LinkedSourcePatchRequest.parse(patch);
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/sources/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);
  return LinkedSource.parse(await res.json());
}

/**
 * POST /api/v1/me/sources/{id}/sync — pull data ngay.
 *
 * Plan §3.4: HTTP 200 KỂ CẢ KHI sync fail (adapter unreachable, decrypt fail).
 * Caller phải kiểm `result.error !== null` thay vì dựa HTTP status.
 * Riêng linked_source không tồn tại / sai owner → 404 (route fail, không phải
 * sync fail) và rơi vào _throwProblem.
 *
 * @param {string} id
 * @returns {Promise<SyncResultT>}
 */
export async function syncSource(id) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/me/sources/${id}/sync`,
    { method: "POST" },
  );
  if (!res.ok) await _throwProblem(res);
  return SyncResult.parse(await res.json());
}

/**
 * GET /api/v1/me/sources/{id}/live-pull?since=ISO — view-only pull cho
 * "Theo dõi trực tiếp". KHÔNG ghi DB. Chỉ hỗ trợ lpwanmapper hiện tại.
 * SourceError (auth/network) → 502 → _throwProblem → caller catch + toast.
 *
 * @param {string} id linked_source UUID
 * @param {string | null} [since] ISO timestamp; null = full snapshot
 */
export async function livePullSource(id, since = null) {
  const params = new URLSearchParams();
  if (since) params.set("since", since);
  const qs = params.toString();
  const url =
    `${API_BASE_URL}/api/v1/me/sources/${id}/live-pull` +
    (qs ? `?${qs}` : "");
  const res = await authFetch(url);
  if (!res.ok) await _throwProblem(res);
  // Reuse SurveyTrainingList zod schema từ api/client.js (cùng shape)
  const { SurveyTrainingList } = await import("../api/client.js");
  return SurveyTrainingList.parse(await res.json());
}

// ── Endpoints: upload batches (refactor 2026-06-11) ───────────────────────

/**
 * POST /api/v1/me/uploads/csv — multipart upload CSV/JSON survey.
 *
 * Refactor 2026-06-11: upload LUÔN tạo batch private, không còn checkbox
 * "đóng góp". User bấm "Đóng góp" trên 1 batch sau đó (xem submitUploadBatch).
 *
 * @param {File} file
 * @returns {Promise<CsvUploadResponseT>}
 */
export async function uploadMeasurementsCsv(file) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/uploads/csv`, {
    method: "POST",
    body: fd,
    // KHÔNG set content-type: browser tự thêm boundary cho multipart/form-data.
  });
  if (!res.ok) await _throwProblem(res);
  return CsvUploadResponse.parse(await res.json());
}

/**
 * GET /api/v1/me/uploads/overview — card "Tổng quan" trang Dữ liệu của tôi.
 *
 * @returns {Promise<z.infer<typeof UploadOverviewResponse>>}
 */
export async function fetchUploadOverview() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/me/uploads/overview`);
  if (!res.ok) await _throwProblem(res);
  return UploadOverviewResponse.parse(await res.json());
}

/**
 * GET /api/v1/me/uploads/batches?include_deleted=...
 *
 * `includeDeleted=false` (Quản lý dữ liệu): chỉ batch còn sống.
 * `includeDeleted=true` (Lịch sử upload, default): bao gồm batch deleted.
 *
 * @param {{ includeDeleted?: boolean }} [opts]
 * @returns {Promise<UploadBatchItemT[]>}
 */
export async function listUploadBatches(opts = {}) {
  const url = new URL(`${API_BASE_URL}/api/v1/me/uploads/batches`);
  if (opts.includeDeleted === false) {
    url.searchParams.set("include_deleted", "false");
  }
  const res = await authFetch(url.toString());
  if (!res.ok) await _throwProblem(res);
  const parsed = UploadBatchListResponse.parse(await res.json());
  return parsed.items;
}

/**
 * POST /api/v1/me/uploads/batches/{id}/submit — đóng góp 1 batch cho cộng
 * đồng (admin duyệt). Idempotent: re-call → queued=0.
 *
 * 403 email_not_verified khi user chưa xác thực email.
 *
 * @param {string} batchId
 * @returns {Promise<UploadBatchSubmitResponseT>}
 */
export async function submitUploadBatch(batchId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/me/uploads/batches/${batchId}/submit`,
    { method: "POST" },
  );
  if (!res.ok) await _throwProblem(res);
  return UploadBatchSubmitResponse.parse(await res.json());
}

/**
 * DELETE /api/v1/me/uploads/batches/{id} — soft-delete batch + hard-purge
 * rows con (quarantine + training). 404 nếu batch không tồn tại / đã xoá.
 *
 * @param {string} batchId
 * @returns {Promise<UploadBatchDeleteResponseT>}
 */
export async function deleteUploadBatch(batchId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/me/uploads/batches/${batchId}`,
    { method: "DELETE" },
  );
  if (!res.ok) await _throwProblem(res);
  return UploadBatchDeleteResponse.parse(await res.json());
}
