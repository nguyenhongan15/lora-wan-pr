// @ts-check
// authFetch — fetch wrapper auto-attach Bearer + clear store khi 401.
//
// Tại sao tách module:
//   - client.js (auth) chỉ login/register/me — không cần token cho 2 cái đầu.
//   - Code khác (api/client.js, future me/sources, admin) cần authFetch
//     để gắn token + xử lý expiry tự động.
//
// 401 → store.clear():
//   Plan §13 risk #6 (token revoke). Khi backend trả 401 (token sai/hết hạn/
//   user bị disabled), xoá session ngay → UI re-render về Login. Caller vẫn
//   nhận Error để hiển thị message.
//
// CHƯA wrap retry/refresh: v1 không có refresh token (plan §14 defer v2).

import { getToken, clear } from "./store.js";

/**
 * fetch + Authorization header (nếu có token) + auto-clear khi 401.
 *
 * @param {string | URL} url
 * @param {RequestInit=} init
 * @returns {Promise<Response>}
 */
export async function authFetch(url, init) {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);

  const res = await fetch(url, { ...init, headers });
  if (res.status === 401) {
    clear();
  }
  return res;
}
