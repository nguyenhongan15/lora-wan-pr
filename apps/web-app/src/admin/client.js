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
});

/**
 * @typedef {z.infer<typeof UserAdmin>} UserAdminT
 * @typedef {z.infer<typeof UserListAdmin>} UserListAdminT
 * @typedef {z.infer<typeof UserPatchRequest>} UserPatchRequestT
 * @typedef {z.infer<typeof SyncReport>} SyncReportT
 * @typedef {z.infer<typeof AdminStats>} AdminStatsT
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
