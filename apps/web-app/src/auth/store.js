// @ts-check
// Auth state store — persist qua localStorage để reload không mất session.
//
// Trade-off (plan §13 risk #10):
//   localStorage có thể bị đọc bởi XSS. Plan-auth-v1 v1 ban đầu chọn in-memory
//   để tránh; ở đây chấp nhận risk vì project demo (for fun) — UX reload mất
//   session khó dùng. v2 nên đổi sang refresh token + HttpOnly cookie:
//     - access token vẫn in-memory
//     - POST /auth/refresh với credentials:'include' lấy access token mới
//     - backend cần allow_credentials=True + origin whitelist
//
// Storage shape (key = STORAGE_KEY):
//   { "token": "<jwt>", "user": { id, email, is_admin, created_at } }
// Validate qua Zod khi hydrate — garbage / format cũ → bỏ qua, treat như chưa
// đăng nhập (server sẽ 401 nếu token cũ vẫn được attach, authFetch tự clear).
//
// API:
//   getToken() → string | null
//   getUser() → User | null
//   setSession(token, user) → void   (sau login/register thành công)
//   clear() → void                    (logout hoặc 401)
//   subscribe(listener) → unsubscribe (React component re-render)

import { z } from "zod";

export const User = z.object({
  id: z.string().uuid(),
  email: z.string(),
  is_admin: z.boolean(),
  created_at: z.string(),
});

/** @typedef {z.infer<typeof User>} UserT */

const STORAGE_KEY = "lora_coverage_auth";

const PersistedSession = z.object({
  token: z.string().min(1),
  user: User,
});

/** @returns {z.infer<typeof PersistedSession> | null} */
function _hydrate() {
  // SSR / test runner thiếu localStorage → no-op an toàn. Cũng bắt JSON parse
  // / Zod fail (key bị tay người sửa, hoặc version schema cũ).
  if (typeof localStorage === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return PersistedSession.parse(JSON.parse(raw));
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return null;
  }
}

const _initial = _hydrate();

/** @type {string | null} */
let _token = _initial?.token ?? null;
/** @type {UserT | null} */
let _user = _initial?.user ?? null;
/** @type {Set<() => void>} */
const _listeners = new Set();

function _emit() {
  for (const fn of _listeners) fn();
}

export function getToken() {
  return _token;
}

export function getUser() {
  return _user;
}

/**
 * @param {string} token
 * @param {UserT} user
 */
export function setSession(token, user) {
  _token = token;
  _user = user;
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user }));
  }
  _emit();
}

export function clear() {
  _token = null;
  _user = null;
  if (typeof localStorage !== "undefined") {
    localStorage.removeItem(STORAGE_KEY);
  }
  _emit();
}

/**
 * @param {() => void} listener
 * @returns {() => void} unsubscribe
 */
export function subscribe(listener) {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}
