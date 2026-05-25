// @ts-check
// Auth API client — register / login / refresh / logout / bootstrap / fetchMe.
//
// v2 (2026-05-19): refresh token sống trong HttpOnly cookie `lora_refresh`.
// Access JWT (TTL 15 min) trả trong response body, store in-memory. Mọi fetch
// tới `/api/v1/auth/*` set `credentials: "include"` để browser attach/cookie
// cookie tự động.
//
// Schema mirror backend (services/api-service/.../edge/schemas.py):
//   RegisterRequest, LoginRequest, TokenResponse, UserResponse.
// Plan §11 step 9 quyết định KHÔNG codegen — duplicate Zod ↔ Pydantic chấp
// nhận. Khi backend đổi shape, sửa cả 2 nơi (CI integration test sẽ catch).
//
// Lỗi: backend dùng RFC 7807 problem+json (edge/errors.py). ApiError giống
// api/client.js để App layer xử lý 1 chỗ (banner/toast).

import { z } from "zod";
import { setSession, clear, getToken, User } from "./store.js";
import { authFetch } from "./_intercept.js";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// ── Schemas ───────────────────────────────────────────────────────────────

export const RegisterRequest = z.object({
  email: z.string().min(3).max(320),
  password: z.string().min(8).max(128),
});

export const LoginRequest = z.object({
  email: z.string().min(3).max(320),
  password: z.string().min(1).max(128),
});

export const PasswordResetRequestRequest = z.object({
  email: z.string().min(3).max(320),
});

export const PasswordResetConfirmRequest = z.object({
  token: z.string().min(32).max(128),
  new_password: z.string().min(8).max(128),
});

export const EmailVerifyConfirmRequest = z.object({
  token: z.string().min(32).max(128),
});

export const TokenResponse = z.object({
  access_token: z.string(),
  token_type: z.literal("bearer"),
  expires_at: z.string(),
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
 * @typedef {z.infer<typeof RegisterRequest>} RegisterRequestT
 * @typedef {z.infer<typeof LoginRequest>} LoginRequestT
 * @typedef {z.infer<typeof TokenResponse>} TokenResponseT
 * @typedef {z.infer<typeof User>} UserT
 * @typedef {z.infer<typeof ProblemDetails>} ProblemDetailsT
 */

export class ApiError extends Error {
  /** @param {ProblemDetailsT} problem */
  constructor(problem) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    /** @type {ProblemDetailsT} */
    this.problem = problem;
  }
}

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
 * POST /api/v1/auth/register → tạo user (KHÔNG auto-login).
 * @param {RegisterRequestT} req
 * @returns {Promise<UserT>}
 */
export async function register(req) {
  const parsed = RegisterRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);
  return User.parse(await res.json());
}

/**
 * POST /api/v1/auth/login → set refresh cookie + access token, lưu session.
 *
 * @param {LoginRequestT} req
 * @returns {Promise<UserT>}
 */
export async function login(req) {
  const parsed = LoginRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);

  const token = TokenResponse.parse(await res.json());

  // /me để lấy User payload (login response không kèm). Bearer trực tiếp —
  // không qua authFetch để tránh side-effect refresh nếu access vừa expire.
  const meRes = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: { authorization: `Bearer ${token.access_token}` },
  });
  if (!meRes.ok) await _throwProblem(meRes);
  const user = User.parse(await meRes.json());

  setSession(token.access_token, user);
  return user;
}

/**
 * POST /api/v1/auth/refresh → access token mới + rotate cookie.
 * Trả null nếu cookie hết hạn / không có (caller xử lý gracefully).
 *
 * Nên dùng `bootstrap()` thay vì gọi refresh trực tiếp ở UI; refresh ngầm
 * trong authFetch interceptor đã đủ cho 99% trường hợp.
 *
 * @returns {Promise<TokenResponseT | null>}
 */
export async function refresh() {
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (res.status === 401) return null;
  if (!res.ok) await _throwProblem(res);
  return TokenResponse.parse(await res.json());
}

/**
 * POST /api/v1/auth/logout → server revoke refresh token + clear cookie,
 * client clear in-memory store.
 *
 * Idempotent ở server (cookie thiếu = no-op). Network error → vẫn clear local
 * để UI logged-out ngay; server bị orphan token sẽ tự expire sau TTL.
 */
export async function logout() {
  try {
    await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // Mạng lỗi — vẫn clear local. Refresh cookie có thể sống thêm tới TTL,
    // nhưng access in-memory đã clear → next reload sẽ thử refresh, server
    // có thể trả 200 (cookie vẫn valid) — UX không hoàn hảo nhưng acceptable.
  }
  clear();
}

/**
 * App-load hook: khôi phục session từ HttpOnly cookie nếu có.
 * Gọi 1 lần ở App mount; idempotent (resolve sớm nếu đã có session).
 *
 * Single-flight: React StrictMode double-mount effect → bootstrap chạy 2 lần
 * gần như đồng thời. Nếu không dedupe, cả 2 đều thấy `getToken()` null trước
 * khi POST /refresh đầu tiên trả về → 2 POST /auth/refresh song song. Refresh
 * token là single-use rotation; call thứ 2 gửi cookie cũ (browser chưa apply
 * Set-Cookie) → backend reuse-detector revoke cả family → reload kế tiếp
 * 100% logged-out. Module-level promise cache khoá callers vào cùng 1 future.
 *
 * @returns {Promise<UserT | null>}
 */
/** @type {Promise<UserT | null> | null} */
let _bootstrapPromise = null;

export async function bootstrap() {
  if (getToken()) return null; // đã có session (HMR hoặc race), không cần
  if (_bootstrapPromise) return _bootstrapPromise;
  _bootstrapPromise = (async () => {
    const token = await refresh();
    if (!token) {
      clear();
      return null;
    }
    const meRes = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
      headers: { authorization: `Bearer ${token.access_token}` },
    });
    if (!meRes.ok) {
      clear();
      return null;
    }
    const user = User.parse(await meRes.json());
    setSession(token.access_token, user);
    return user;
  })();
  _bootstrapPromise.finally(() => {
    _bootstrapPromise = null;
  });
  return _bootstrapPromise;
}

/**
 * POST /api/v1/auth/password-reset/request — fire-and-forget.
 *
 * Backend always-204: không leak email registered/disabled. UI hiển thị
 * cùng confirmation message dù email có tồn tại hay không.
 *
 * @param {{ email: string }} req
 * @returns {Promise<void>}
 */
export async function requestPasswordReset(req) {
  const parsed = PasswordResetRequestRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/password-reset/request`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  // 204 = thành công; 429 = rate limit; 422 = email shape sai (Zod catch
  // trước). 4xx khác chỉ ApiError, không có 2xx nào ngoài 204.
  if (!res.ok) await _throwProblem(res);
}

/**
 * POST /api/v1/auth/password-reset/confirm — single-use, kick toàn bộ phiên.
 *
 * Sau confirm: backend revoke tất cả refresh tokens; FE phải clear() store
 * và yêu cầu user login lại với password mới.
 *
 * @param {{ token: string, new_password: string }} req
 * @returns {Promise<void>}
 */
export async function confirmPasswordReset(req) {
  const parsed = PasswordResetConfirmRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/password-reset/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);
  // Mọi session hiện tại của user này đã bị revoke ở backend → clear local
  // store nếu trùng user. Đơn giản nhất là clear vô điều kiện — UX an toàn.
  clear();
}

/**
 * POST /api/v1/auth/email-verify/request — auth required, fire-and-forget.
 *
 * Backend gửi email kèm link verify. Token TTL 60 phút. Rate-limited 5/hour
 * per IP. Idempotent về UX — user xác thực rồi gọi lại = no-op (server
 * skip mail send).
 *
 * @returns {Promise<void>}
 */
export async function requestEmailVerification() {
  const res = await authFetch(`${API_BASE_URL}/api/v1/auth/email-verify/request`, {
    method: "POST",
  });
  if (!res.ok) await _throwProblem(res);
}

/**
 * POST /api/v1/auth/email-verify/confirm — single-use.
 *
 * KHÔNG gọi fetchMe ở đây: confirm page sẽ tự refresh session trong effect
 * sau khi mutation isSuccess. Inline fetchMe trong mutation từng gây stuck
 * "Đang xác thực…" khi authFetch race với bootstrap refresh.
 *
 * @param {{ token: string }} req
 * @returns {Promise<void>}
 */
export async function confirmEmailVerification(req) {
  const parsed = EmailVerifyConfirmRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/email-verify/confirm`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);
}

/**
 * GET /api/v1/auth/me — refresh user payload (e.g. sau khi admin disable).
 * Trả null nếu chưa có token (caller tự decide có gọi không).
 *
 * @returns {Promise<UserT | null>}
 */
export async function fetchMe() {
  if (!getToken()) return null;
  const res = await authFetch(`${API_BASE_URL}/api/v1/auth/me`);
  if (res.status === 401) {
    // authFetch đã thử refresh + clear nếu fail.
    return null;
  }
  if (!res.ok) await _throwProblem(res);
  return User.parse(await res.json());
}
