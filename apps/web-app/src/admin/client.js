// @ts-check
// Admin API client — wrap 4 endpoint /api/v1/admin/*.
//
// Mọi route gắn `require_admin` ở backend → 401 (chưa đăng nhập / token sai)
// hoặc 403 (admin_required) khi token hợp lệ nhưng không phải admin. Cả hai
// đi qua _intercept.authFetch — 401 tự clear store. 403 thì authFetch giữ
// session, để FE hiển thị error và App giữ tab admin (admin user mất quyền
// giữa session là edge case, không cần auto-logout).
//
// Schema mirror Pydantic ở edge/schemas.py — duplicate có chủ ý theo plan
// §11 step 9 (no codegen). Đổi shape sửa cả 2, integration test catch lệch.
//
// Self-protection (admin sửa is_admin/disabled chính mình → 400
// admin_self_modification) backend đã chặn — FE thêm UI guard ẩn nút trên
// row của self để người dùng KHÔNG bao giờ chạm vào lỗi đó (UX > error
// recovery).

import { z } from "zod";
import { ApiError, ProblemDetails } from "../auth/client.js";
import { authFetch } from "../auth/_intercept.js";
import { SyncResult } from "../sources/client.js";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ── Schemas ───────────────────────────────────────────────────────────────

export const UserAdmin = z.object({
  id: z.string().uuid(),
  email: z.string(),
  is_admin: z.boolean(),
  disabled: z.boolean(),
  created_at: z.string(),
  contribution_count: z.number().int().nonnegative(),
});

export const UserListAdmin = z.object({
  items: z.array(UserAdmin),
  total: z.number().int().nonnegative(),
});

export const UserPatchRequest = z
  .object({
    is_admin: z.boolean().optional(),
    disabled: z.boolean().optional(),
  })
  .refine(
    (obj) => obj.is_admin !== undefined || obj.disabled !== undefined,
    { message: "PATCH cần ít nhất 1 field" },
  );

export const SyncReport = z.object({
  items: z.array(SyncResult),
  total: z.number().int().nonnegative(),
  successes: z.number().int().nonnegative(),
  failures: z.number().int().nonnegative(),
});

export const AdminStats = z.object({
  user_count: z.number().int().nonnegative(),
  active_user_count: z.number().int().nonnegative(),
  linked_source_count: z.number().int().nonnegative(),
  active_source_count: z.number().int().nonnegative(),
  gateway_count: z.number().int().nonnegative(),
  measurement_count: z.number().int().nonnegative(),
  pending_review_count: z.number().int().nonnegative(),
});

export const PendingContribution = z.object({
  id: z.string().uuid(),
  timestamp: z.string(),
  submitted_at: z.string(),
  latitude: z.number(),
  longitude: z.number(),
  rssi_dbm: z.number(),
  snr_db: z.number(),
  spreading_factor: z.number().int(),
  frequency_mhz: z.number(),
  source_type: z.string().nullable(),
  contributor_user_id: z.string().uuid().nullable(),
  contributor_email: z.string().nullable(),
  serving_gateway_id: z.string().uuid().nullable(),
  gateway_code: z.string().nullable(),
  linked_source_id: z.string().uuid().nullable(),
});

export const PendingContributionList = z.object({
  items: z.array(PendingContribution),
  total: z.number().int().nonnegative(),
});

export const ContributionReview = z.object({
  id: z.string().uuid(),
  review_status: z.enum(["approved", "rejected"]),
});

export const PendingReviewBatch = z.object({
  uploader_id: z.string().uuid(),
  uploader_email: z.string().nullable(),
  uploaded_at: z.string(),
  pending_review_count: z.number().int().nonnegative(),
  total_count: z.number().int().nonnegative(),
  earliest_timestamp: z.string(),
  latest_timestamp: z.string(),
});

export const PendingReviewBatchList = z.object({
  items: z.array(PendingReviewBatch),
});

export const BatchReviewResponse = z.object({
  uploader_id: z.string().uuid(),
  uploaded_at: z.string(),
  approved_count: z.number().int().nonnegative().default(0),
  rejected_count: z.number().int().nonnegative().default(0),
});

/**
 * @typedef {z.infer<typeof UserAdmin>} UserAdminT
 * @typedef {z.infer<typeof UserListAdmin>} UserListAdminT
 * @typedef {z.infer<typeof UserPatchRequest>} UserPatchRequestT
 * @typedef {z.infer<typeof SyncReport>} SyncReportT
 * @typedef {z.infer<typeof AdminStats>} AdminStatsT
 * @typedef {z.infer<typeof PendingContribution>} PendingContributionT
 * @typedef {z.infer<typeof PendingContributionList>} PendingContributionListT
 * @typedef {z.infer<typeof ContributionReview>} ContributionReviewT
 * @typedef {z.infer<typeof PendingReviewBatch>} PendingReviewBatchT
 * @typedef {z.infer<typeof PendingReviewBatchList>} PendingReviewBatchListT
 * @typedef {z.infer<typeof BatchReviewResponse>} BatchReviewResponseT
 */

// ── Helpers ───────────────────────────────────────────────────────────────

/**
 * @param {Response} res
 * @returns {Promise<never>}
 */
async function _throwProblem(res) {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/problem+json") || ct.includes("application/json")) {
    throw new ApiError(ProblemDetails.parse(await res.json()));
  }
  throw new ApiError({
    type: "about:blank",
    title: "HTTP error",
    status: res.status,
  });
}

// ── Endpoints ─────────────────────────────────────────────────────────────

/**
 * GET /api/v1/admin/users — list toàn bộ user kèm contribution_count.
 * @returns {Promise<UserListAdminT>}
 */
export async function listUsers() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/users`);
  if (!res.ok) await _throwProblem(res);
  return UserListAdmin.parse(await res.json());
}

/**
 * PATCH /api/v1/admin/users/{id} — toggle is_admin / disabled.
 *
 * Self-modification → 400 admin_self_modification. UI nên ẩn nút trước khi
 * tới được đây.
 *
 * @param {string} userId UUID
 * @param {UserPatchRequestT} patch
 * @returns {Promise<UserAdminT>}
 */
export async function patchUser(userId, patch) {
  const parsed = UserPatchRequest.parse(patch);
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);
  return UserAdmin.parse(await res.json());
}

/**
 * POST /api/v1/admin/sync — global sync mọi linked_source eligible
 * (status=active + contribute_to_community=true).
 *
 * v1 sync synchronous → có thể chậm khi nhiều source. Caller nên hiển thị
 * spinner. Plan §10 ghi v2 chuyển sang background queue.
 *
 * @returns {Promise<SyncReportT>}
 */
export async function globalSync() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/sync`, {
    method: "POST",
  });
  if (!res.ok) await _throwProblem(res);
  return SyncReport.parse(await res.json());
}

/**
 * GET /api/v1/admin/stats — counters tổng (snapshot, không transactional).
 * @returns {Promise<AdminStatsT>}
 */
export async function getStats() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/stats`);
  if (!res.ok) await _throwProblem(res);
  return AdminStats.parse(await res.json());
}

/**
 * GET /api/v1/admin/contributions/pending — list rows chờ duyệt thủ công.
 * @param {{ limit?: number, offset?: number }} [opts]
 * @returns {Promise<PendingContributionListT>}
 */
export async function listPendingContributions(opts = {}) {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const qs = params.toString() ? `?${params.toString()}` : "";
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/pending${qs}`,
  );
  if (!res.ok) await _throwProblem(res);
  return PendingContributionList.parse(await res.json());
}

/**
 * POST /api/v1/admin/contributions/{id}/approve — đẩy vào survey_training.
 * @param {string} id
 * @returns {Promise<ContributionReviewT>}
 */
export async function approveContribution(id) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/${id}/approve`,
    { method: "POST" },
  );
  if (!res.ok) await _throwProblem(res);
  return ContributionReview.parse(await res.json());
}

/**
 * POST /api/v1/admin/contributions/{id}/reject — đóng góp giữ trong quarantine.
 * @param {string} id
 * @param {string|null} [note]
 * @returns {Promise<ContributionReviewT>}
 */
export async function rejectContribution(id, note = null) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/${id}/reject`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ note }),
    },
  );
  if (!res.ok) await _throwProblem(res);
  return ContributionReview.parse(await res.json());
}

/**
 * GET /api/v1/admin/contributions/batches — list batch (1 file CSV upload =
 * 1 batch) còn rows ở review_status='pending_review'.
 * @returns {Promise<PendingReviewBatchListT>}
 */
export async function listPendingBatches() {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/batches`,
  );
  if (!res.ok) await _throwProblem(res);
  return PendingReviewBatchList.parse(await res.json());
}

/**
 * GET /api/v1/admin/contributions/batches/rows — list rows trong 1 batch
 * (drill-in: admin xem chi tiết từng điểm để có thể reject lẻ trước khi
 * approve cả batch).
 * @param {string} uploaderId UUID
 * @param {string} uploadedAt ISO timestamp (giá trị `uploaded_at` từ batch)
 * @returns {Promise<PendingContributionListT>}
 */
export async function listBatchRows(uploaderId, uploadedAt) {
  const params = new URLSearchParams({
    uploader_id: uploaderId,
    uploaded_at: uploadedAt,
  });
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/batches/rows?${params.toString()}`,
  );
  if (!res.ok) await _throwProblem(res);
  return PendingContributionList.parse(await res.json());
}

/**
 * POST /api/v1/admin/contributions/batches/approve — duyệt toàn bộ rows
 * còn `review_status='pending_review'` trong batch. Email cảm ơn gửi 1 lần
 * (summary).
 * @param {string} uploaderId UUID
 * @param {string} uploadedAt ISO timestamp
 * @returns {Promise<BatchReviewResponseT>}
 */
export async function approveBatch(uploaderId, uploadedAt) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/batches/approve`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        uploader_id: uploaderId,
        uploaded_at: uploadedAt,
      }),
    },
  );
  if (!res.ok) await _throwProblem(res);
  return BatchReviewResponse.parse(await res.json());
}

/**
 * POST /api/v1/admin/contributions/batches/reject — reject hàng loạt mọi
 * row pending trong batch.
 * @param {string} uploaderId
 * @param {string} uploadedAt
 * @param {string|null} [note]
 * @returns {Promise<BatchReviewResponseT>}
 */
export async function rejectBatch(uploaderId, uploadedAt, note = null) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/contributions/batches/reject`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        uploader_id: uploaderId,
        uploaded_at: uploadedAt,
        note,
      }),
    },
  );
  if (!res.ok) await _throwProblem(res);
  return BatchReviewResponse.parse(await res.json());
}
