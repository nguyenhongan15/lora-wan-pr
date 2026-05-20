// @ts-check
// Sources API client — me/sources CRUD + manual sync.
//
// Mirror Pydantic schemas (services/api-service/.../edge/schemas.py
// "Linking — me/sources" + "Sync"). Zod ↔ Pydantic duplicate cố ý: plan-auth
// §11 step 9 quyết định KHÔNG codegen — đổi shape sửa cả 2, CI integration
// test catch lệch.
//
// Tất cả endpoint cần Bearer → authFetch (auth/_intercept.js). authFetch tự
// clear store khi 401 → UI fall back về Login modal.
//
// ApiError + ProblemDetails reuse từ auth/client.js (1 lớp lỗi xuyên app).

import { z } from "zod";
import { ApiError, ProblemDetails } from "../auth/client.js";
import { authFetch } from "../auth/_intercept.js";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ── Schemas ───────────────────────────────────────────────────────────────

export const LinkedSource = z.object({
  id: z.string().uuid(),
  source_type: z.string(),
  label: z.string(),
  status: z.enum(["active", "paused", "failed"]),
  contribute_to_community: z.boolean(),
  contributed_at: z.string().nullable(),
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

export const LinkedSourcePatchRequest = z
  .object({
    contribute_to_community: z.boolean().optional(),
    status: z.enum(["active", "paused"]).optional(),
  })
  .refine(
    (obj) =>
      obj.contribute_to_community !== undefined || obj.status !== undefined,
    { message: "PATCH cần ít nhất 1 field" },
  );

export const SyncResult = z.object({
  linked_source_id: z.string().uuid(),
  gateways_inserted: z.number().int().nonnegative(),
  gateways_updated: z.number().int().nonnegative(),
  measurements_inserted: z.number().int().nonnegative(),
  measurements_updated: z.number().int().nonnegative(),
  devices_inserted: z.number().int().nonnegative(),
  devices_updated: z.number().int().nonnegative(),
  last_sync_at: z.string().nullable(),
  error: z.string().nullable(),
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

// ── Endpoints ─────────────────────────────────────────────────────────────

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
 * PATCH /api/v1/me/sources/{id} — toggle contribute và/hoặc status.
 * Cả 2 None → backend 400. Schema refine ở client cũng chặn trước.
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
