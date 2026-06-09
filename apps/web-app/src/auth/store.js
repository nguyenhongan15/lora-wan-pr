// @ts-check
// Auth state store — IN-MEMORY only.
//
// v2 (2026-05-19): bỏ localStorage. Refresh token nằm trong HttpOnly cookie
// `lora_refresh` (path-scoped /api/v1/auth). Access JWT (TTL 15 min) chỉ
// sống in-memory → reload trang sẽ rỗng → App boostrap gọi /auth/refresh để
// rehydrate session từ cookie (xem `client.bootstrap`). Trade-off:
//   - Pros: XSS không đọc được token (refresh trong HttpOnly cookie; access
//     trong closure JS không persist).
//   - Cons: First paint sau reload thấy logged-out ~50ms cho tới khi bootstrap
//     trả về. Chấp nhận được — UX cooldown trong khoảng tin cậy.
//
// API giữ nguyên signature để callers không phải đổi:
//   getToken() → string | null
//   getUser() → User | null
//   setSession(token, user) → void
//   clear() → void
//   subscribe(listener) → unsubscribe

import { z } from "zod";

export const User = z.object({
  id: z.string().uuid(),
  email: z.string(),
  is_admin: z.boolean(),
  is_super_admin: z.boolean().default(false),
  email_verified: z.boolean(),
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
