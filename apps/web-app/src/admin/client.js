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

// Xem ghi chú ở api/client.js: localhost → 8000 cho dev, ngược lại theo env.
const API_BASE_URL = (() => {
  if (typeof window !== "undefined") {
    const h = window.location.hostname;
    if (h === "localhost" || h === "127.0.0.1") return "http://localhost:8000";
  }
  return import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
})();

// ── Schemas ───────────────────────────────────────────────────────────────

export const UserAdmin = z.object({
  id: z.string().uuid(),
  email: z.string(),
  is_admin: z.boolean(),
  is_super_admin: z.boolean().default(false),
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
  online_user_count: z.number().int().nonnegative(),
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

export const CoverageRebuildEnqueue = z.object({
  job_id: z.string().uuid(),
  status: z.literal("queued"),
});

export const CoverageRebuildJob = z.object({
  id: z.string().uuid(),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  triggered_by: z.string().uuid().nullable(),
  triggered_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  gateways_total: z.number().int().nullable(),
  gateways_rebuilt: z.number().int().nonnegative(),
  gateways_skipped: z.number().int().nonnegative(),
  per_gw_log: z.record(z.any()),
  error_text: z.string().nullable(),
  celery_task_id: z.string().nullable(),
});

export const CoverageRebuildJobList = z.object({
  items: z.array(CoverageRebuildJob),
});

// ── Training batch audit (admin trace-back) ──────────────────────────────

export const TrainingBatchItem = z.object({
  batch_id: z.string().uuid(),
  uploader_id: z.string().uuid(),
  uploader_email: z.string().nullable(),
  uploader_is_admin: z.boolean().default(false),
  uploader_is_super_admin: z.boolean().default(false),
  kind: z
    .enum(["csv", "json", "sync_lpwanmapper", "sync_chirpstack", "live_session"])
    .nullable(),
  filename: z.string().nullable(),
  uploaded_at: z.string().nullable(),
  promoted_count: z.number().int().nonnegative(),
  latest_approved_at: z.string(),
  batch_deleted_at: z.string().nullable(),
});

export const TrainingBatchList = z.object({
  items: z.array(TrainingBatchItem),
});

export const TrainingBatchDelete = z.object({
  batch_id: z.string().uuid(),
  deleted_count: z.number().int().nonnegative(),
});

// ── ML retrain (mirror CoverageRebuild) ──────────────────────────────────

export const MlRetrainEnqueue = z.object({
  job_id: z.string().uuid(),
  status: z.literal("queued"),
});

export const MlRetrainJob = z.object({
  id: z.string().uuid(),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  triggered_by: z.string().uuid().nullable(),
  triggered_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  rows_trained: z.number().int().nullable(),
  artifact_path: z.string().nullable(),
  metrics: z.record(z.any()),
  error_text: z.string().nullable(),
  celery_task_id: z.string().nullable(),
  report_dir: z.string().nullable().optional(),
});

export const MlRetrainJobList = z.object({
  items: z.array(MlRetrainJob),
});

export const DataFreshness = z.object({
  threshold: z.number().int(),
  last_rebuild_finished_at: z.string().nullable(),
  new_points_since_rebuild: z.number().int(),
  needs_rebuild: z.boolean(),
  last_retrain_finished_at: z.string().nullable(),
  new_points_since_retrain: z.number().int(),
  needs_retrain: z.boolean(),
});

export const TimeseriesPoint = z.object({
  bucket_start: z.string(),
  count: z.number().int(),
});

export const TimeseriesResponseSchema = z.object({
  metric: z.enum(["visits", "signups", "training_points"]),
  bucket: z.enum(["week", "month", "year"]),
  items: z.array(TimeseriesPoint),
});

export const TopGatewayItem = z.object({
  gateway_code: z.string(),
  name: z.string().nullable(),
  training_count: z.number().int(),
});

export const TopGatewayResponseSchema = z.object({
  items: z.array(TopGatewayItem),
});

// ── Gateway moderation (geo.gateway_quarantine) ──────────────────────────

export const PendingGateway = z.object({
  id: z.string().uuid(),
  code: z.string(),
  name: z.string(),
  latitude: z.number(),
  longitude: z.number(),
  altitude_m: z.number(),
  frequency_mhz: z.number(),
  source_type: z.string(),
  contributor_user_id: z.string().uuid().nullable(),
  contributor_email: z.string().nullable(),
  linked_source_id: z.string().uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const PendingGatewayList = z.object({
  items: z.array(PendingGateway),
  total: z.number().int().nonnegative(),
});

export const GatewayApprove = z.object({
  quarantine_id: z.string().uuid(),
  gateway_id: z.string().uuid(),
  measurements_backfilled: z.number().int().nonnegative(),
});

export const GatewayReject = z.object({
  quarantine_id: z.string().uuid(),
  review_status: z.literal("rejected"),
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
 * @typedef {z.infer<typeof CoverageRebuildEnqueue>} CoverageRebuildEnqueueT
 * @typedef {z.infer<typeof CoverageRebuildJob>} CoverageRebuildJobT
 * @typedef {z.infer<typeof CoverageRebuildJobList>} CoverageRebuildJobListT
 * @typedef {z.infer<typeof TrainingBatchItem>} TrainingBatchItemT
 * @typedef {z.infer<typeof TrainingBatchList>} TrainingBatchListT
 * @typedef {z.infer<typeof TrainingBatchDelete>} TrainingBatchDeleteT
 * @typedef {z.infer<typeof MlRetrainEnqueue>} MlRetrainEnqueueT
 * @typedef {z.infer<typeof MlRetrainJob>} MlRetrainJobT
 * @typedef {z.infer<typeof MlRetrainJobList>} MlRetrainJobListT
 * @typedef {z.infer<typeof DataFreshness>} DataFreshnessT
 * @typedef {z.infer<typeof TimeseriesResponseSchema>} TimeseriesResponseT
 * @typedef {z.infer<typeof TopGatewayResponseSchema>} TopGatewayResponseT
 * @typedef {z.infer<typeof PendingGateway>} PendingGatewayT
 * @typedef {z.infer<typeof PendingGatewayList>} PendingGatewayListT
 * @typedef {z.infer<typeof GatewayApprove>} GatewayApproveT
 * @typedef {z.infer<typeof GatewayReject>} GatewayRejectT
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
 * DELETE /api/v1/admin/users/{id} — xoá hard user. CHỈ super admin (backend
 * `require_super_admin` gate). 204 thành công, 400 self-modification, 404
 * không tồn tại, 403 admin thường thử gọi.
 *
 * Destructive: CASCADE token rows; SET NULL contribution rows (data giữ
 * trên map cộng đồng với contributor_user_id = NULL). Reuse `Xoá tài khoản
 * vĩnh viễn` cảnh báo ở UI confirm.
 *
 * @param {string} userId UUID
 * @returns {Promise<void>}
 */
export async function deleteUser(userId) {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/users/${userId}`, {
    method: "DELETE",
  });
  if (!res.ok) await _throwProblem(res);
}

/**
 * POST /api/v1/admin/sync — global sync mọi linked_source eligible
 * (status=active).
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

/**
 * POST /api/v1/admin/coverage/rebuild — enqueue Celery task, response 202.
 * @returns {Promise<CoverageRebuildEnqueueT>}
 */
export async function enqueueCoverageRebuild() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/coverage/rebuild`, {
    method: "POST",
  });
  if (!res.ok) await _throwProblem(res);
  return CoverageRebuildEnqueue.parse(await res.json());
}

/**
 * GET /api/v1/admin/coverage/rebuild/{job_id} — poll status.
 * @param {string} jobId UUID
 * @returns {Promise<CoverageRebuildJobT>}
 */
export async function getCoverageRebuildJob(jobId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/coverage/rebuild/${jobId}`,
  );
  if (!res.ok) await _throwProblem(res);
  return CoverageRebuildJob.parse(await res.json());
}

/**
 * GET /api/v1/admin/coverage/rebuild/latest — toàn bộ lịch sử rebuild.
 * @returns {Promise<CoverageRebuildJobListT>}
 */
export async function listRecentCoverageRebuilds() {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/coverage/rebuild/latest`,
  );
  if (!res.ok) await _throwProblem(res);
  return CoverageRebuildJobList.parse(await res.json());
}

/**
 * GET /api/v1/admin/training/batches — list batch đã có rows trong
 * ts.survey_training (admin trace-back data đã duyệt).
 * @returns {Promise<TrainingBatchListT>}
 */
export async function listTrainingBatches() {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/training/batches`,
  );
  if (!res.ok) await _throwProblem(res);
  return TrainingBatchList.parse(await res.json());
}

/**
 * DELETE /api/v1/admin/training/batches/{batch_id} — xoá hết training rows
 * của batch. Quarantine không bị động.
 * @param {string} batchId UUID
 * @returns {Promise<TrainingBatchDeleteT>}
 */
export async function deleteTrainingBatch(batchId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/training/batches/${batchId}`,
    { method: "DELETE" },
  );
  if (!res.ok) await _throwProblem(res);
  return TrainingBatchDelete.parse(await res.json());
}

/**
 * POST /api/v1/admin/ml/retrain — enqueue Celery task, response 202.
 * @returns {Promise<MlRetrainEnqueueT>}
 */
export async function enqueueMlRetrain() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/ml/retrain`, {
    method: "POST",
  });
  if (!res.ok) await _throwProblem(res);
  return MlRetrainEnqueue.parse(await res.json());
}

/**
 * GET /api/v1/admin/ml/retrain/{job_id} — poll status.
 * @param {string} jobId UUID
 * @returns {Promise<MlRetrainJobT>}
 */
export async function getMlRetrainJob(jobId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/ml/retrain/${jobId}`,
  );
  if (!res.ok) await _throwProblem(res);
  return MlRetrainJob.parse(await res.json());
}

/**
 * GET /api/v1/admin/ml/retrain/latest — 5 lần retrain gần nhất.
 * @returns {Promise<MlRetrainJobListT>}
 */
export async function listRecentMlRetrains() {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/ml/retrain/latest`,
  );
  if (!res.ok) await _throwProblem(res);
  return MlRetrainJobList.parse(await res.json());
}

/**
 * GET /api/v1/admin/ml/retrain/{job_id}/report — HTML báo cáo (inline, ảnh
 * embed base64). authFetch để gắn Bearer; trả blob caller tự handle (open
 * trong tab mới qua object URL).
 *
 * @param {string} jobId UUID
 * @returns {Promise<Blob>}
 */
export async function fetchMlRetrainReportHtml(jobId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/ml/retrain/${jobId}/report`,
  );
  if (!res.ok) await _throwProblem(res);
  return res.blob();
}

/**
 * GET /api/v1/admin/ml/retrain/{job_id}/report.pdf — PDF báo cáo.
 *
 * @param {string} jobId UUID
 * @returns {Promise<Blob>}
 */
export async function fetchMlRetrainReportPdf(jobId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/ml/retrain/${jobId}/report.pdf`,
  );
  if (!res.ok) await _throwProblem(res);
  return res.blob();
}

/**
 * GET /api/v1/admin/notifications/data-freshness — đếm điểm đo training mới
 * kể từ rebuild + retrain succeeded gần nhất.
 * @returns {Promise<DataFreshnessT>}
 */
export async function getDataFreshness() {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/notifications/data-freshness`,
  );
  if (!res.ok) await _throwProblem(res);
  return DataFreshness.parse(await res.json());
}

/**
 * GET /api/v1/admin/stats/timeseries — time-series cho chart Tổng quan.
 * @param {"visits"|"signups"|"training_points"} metric
 * @param {"week"|"month"|"year"} bucket
 * @returns {Promise<TimeseriesResponseT>}
 */
export async function getStatsTimeseries(metric, bucket) {
  const url = new URL(`${API_BASE_URL}/api/v1/admin/stats/timeseries`);
  url.searchParams.set("metric", metric);
  url.searchParams.set("bucket", bucket);
  const res = await authFetch(url.toString());
  if (!res.ok) await _throwProblem(res);
  return TimeseriesResponseSchema.parse(await res.json());
}

/**
 * GET /api/v1/admin/stats/top-gateways — top 5 gateway theo số điểm đo training.
 * @returns {Promise<TopGatewayResponseT>}
 */
export async function getTopGateways() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/admin/stats/top-gateways`);
  if (!res.ok) await _throwProblem(res);
  return TopGatewayResponseSchema.parse(await res.json());
}

/**
 * GET /api/v1/admin/gateway-contributions/pending — gateway chờ duyệt
 * (geo.gateway_quarantine review_status='pending_review').
 * @returns {Promise<PendingGatewayListT>}
 */
export async function listPendingGateways() {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/gateway-contributions/pending`,
  );
  if (!res.ok) await _throwProblem(res);
  return PendingGatewayList.parse(await res.json());
}

/**
 * POST /api/v1/admin/gateway-contributions/{quarantine_id}/approve —
 * promote quarantine row → geo.gateways, backfill measurement FK.
 * @param {string} quarantineId UUID
 * @returns {Promise<GatewayApproveT>}
 */
export async function approveGateway(quarantineId) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/gateway-contributions/${quarantineId}/approve`,
    { method: "POST" },
  );
  if (!res.ok) await _throwProblem(res);
  return GatewayApprove.parse(await res.json());
}

/**
 * POST /api/v1/admin/gateway-contributions/{quarantine_id}/reject —
 * giữ row trong quarantine với review_status='rejected'.
 * @param {string} quarantineId UUID
 * @param {string|null} [note]
 * @returns {Promise<GatewayRejectT>}
 */
export async function rejectGateway(quarantineId, note = null) {
  const res = await authFetch(
    `${API_BASE_URL}/api/v1/admin/gateway-contributions/${quarantineId}/reject`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ note }),
    },
  );
  if (!res.ok) await _throwProblem(res);
  return GatewayReject.parse(await res.json());
}
