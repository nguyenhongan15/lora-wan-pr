// @ts-check
// Auth API client — register / login / logout / fetchMe.
//
// Tại sao tách khỏi api/client.js:
//   * Concern khác: identity vs coverage/gateway.
//   * Login + register KHÔNG cần Bearer (chưa có token). fetchMe CẦN → dùng
//     authFetch. Mixing trong api/client.js sẽ rối.
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
 * POST /api/v1/auth/login → set session vào store, trả về user.
 * Caller chỉ cần `await login(...)` — store đã update, subscribe sẽ fire.
 *
 * @param {LoginRequestT} req
 * @returns {Promise<UserT>}
 */
export async function login(req) {
  const parsed = LoginRequest.parse(req);
  const res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(parsed),
  });
  if (!res.ok) await _throwProblem(res);

  const token = TokenResponse.parse(await res.json());

  // Token có rồi nhưng chưa có user payload (TokenResponse không kèm user
  // info). Gọi /me ngay để lấy User → set 1 lần cả 2.
  const meRes = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
    headers: { authorization: `Bearer ${token.access_token}` },
  });
  if (!meRes.ok) await _throwProblem(meRes);
  const user = User.parse(await meRes.json());

  setSession(token.access_token, user);
  return user;
}

/**
 * Logout — purely client-side. v1 KHÔNG có /auth/logout (plan §14: no
 * server-side revoke list — token expire tự nhiên trong 60 phút).
 */
export function logout() {
  clear();
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
    // authFetch đã clear store rồi.
    return null;
  }
  if (!res.ok) await _throwProblem(res);
  return User.parse(await res.json());
}
