// @ts-check
// Auth state store — in-memory only (KHÔNG localStorage / sessionStorage).
//
// Tại sao in-memory:
//   plan-auth-v1 §13 risk #10 — XSS sẽ đọc được token nếu lưu trong
//   localStorage. v1 chưa có refresh token (plan §14 defer v2). Trade-off:
//   user reload/đóng tab → mất token → phải login lại.
//
// Khi v2 thêm refresh token (HttpOnly cookie):
//   - access token vẫn in-memory (đây)
//   - frontend gọi POST /auth/refresh với credentials:'include' → backend
//     đọc HttpOnly cookie → trả access token mới → set vào store đây
//   - backend cần `allow_credentials=True` + origin whitelist (sửa CORS)
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

/** @type {string | null} */
let _token = null;
/** @type {UserT | null} */
let _user = null;
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
  _emit();
}

export function clear() {
  _token = null;
  _user = null;
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
