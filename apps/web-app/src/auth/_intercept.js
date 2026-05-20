// @ts-check
// authFetch — fetch wrapper attach Bearer + auto-refresh trên 401.
//
// v2 (2026-05-19): single-flight refresh. Khi response 401 (không phải từ
// `/api/v1/auth/*`), gọi `/api/v1/auth/refresh` 1 lần — nếu thành công thì
// retry request gốc với access token mới; thất bại → clear store (User về
// trạng thái logged-out, UI re-render).
//
// Single-flight: nhiều request song song 401 cùng lúc (Map + Heatmap + Gateway
// list) phải dedupe để chỉ có 1 POST /refresh, tránh race tạo nhiều cặp
// rotation chain (server sẽ revoke family nếu thấy reuse — false positive nguy
// hiểm). Promise được cache trong `_refreshPromise`; mọi caller chờ cùng 1
// future.
//
// `credentials: "include"` bắt buộc — refresh token đi qua HttpOnly cookie.
// Backend CORS đã set `allow_credentials=True` + strict whitelist (không có
// dấu `*`).

import { getToken, getUser, setSession, clear } from "./store.js";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/** @type {Promise<boolean> | null} */
let _refreshPromise = null;

/**
 * Cố gắng refresh access token bằng cookie `lora_refresh`. Single-flight:
 * concurrent callers chia sẻ cùng 1 promise.
 *
 * Trả `true` nếu refresh OK + store đã setSession; `false` nếu cookie hết hạn /
 * thiếu / bị revoke / bất kỳ lỗi mạng nào (caller nên clear store).
 *
 * @returns {Promise<boolean>}
 */
function _refreshOnce() {
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) return false;
      const body = await res.json();
      const newToken = body?.access_token;
      if (typeof newToken !== "string") return false;

      // User payload không kèm trong refresh response. Reuse User cũ nếu có
      // (admin disable check vẫn chạy ở backend mỗi /me + mỗi endpoint cần
      // auth — store hoá rỗng nếu user bị disable). Nếu store rỗng (bootstrap
      // path) → fetch /me bằng token mới.
      const existingUser = getUser();
      if (existingUser) {
        setSession(newToken, existingUser);
        return true;
      }
      const meRes = await fetch(`${API_BASE_URL}/api/v1/auth/me`, {
        headers: { authorization: `Bearer ${newToken}` },
      });
      if (!meRes.ok) return false;
      const user = await meRes.json();
      setSession(newToken, user);
      return true;
    } catch {
      return false;
    }
  })();
  // Reset slot ngay sau khi resolve để lần 401 tiếp theo (token mới expire
  // 15 min sau) lại được fresh refresh, không stale cache.
  _refreshPromise.finally(() => {
    _refreshPromise = null;
  });
  return _refreshPromise;
}

/**
 * fetch + Authorization header (nếu có token) + auto-refresh trên 401.
 *
 * @param {string | URL} url
 * @param {RequestInit=} init
 * @returns {Promise<Response>}
 */
export async function authFetch(url, init) {
  const urlStr = String(url);
  // KHÔNG trigger refresh khi gọi /auth/* — refresh tự lo bằng cookie, các
  // route khác (login/register) không phải target của Bearer expiry. Tránh
  // recursion: refresh trả 401 mà retry refresh nữa → loop.
  const isAuthRoute = urlStr.includes("/api/v1/auth/");

  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("authorization", `Bearer ${token}`);

  const firstRes = await fetch(url, { ...init, headers, credentials: "include" });

  if (firstRes.status !== 401) return firstRes;

  if (isAuthRoute) {
    // 401 từ /auth/me hoặc /auth/refresh → coi như logged out.
    clear();
    return firstRes;
  }

  const refreshed = await _refreshOnce();
  if (!refreshed) {
    clear();
    return firstRes;
  }

  // Retry request gốc với token mới. JSON body là string → safe re-fetch.
  const newToken = getToken();
  const retryHeaders = new Headers(init?.headers);
  if (newToken) retryHeaders.set("authorization", `Bearer ${newToken}`);
  return fetch(url, { ...init, headers: retryHeaders, credentials: "include" });
}
