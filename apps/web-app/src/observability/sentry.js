// @ts-check
/**
 * Sentry FE wrapper — env-gated. Khi `VITE_SENTRY_DSN` rỗng (dev / chưa cấu
 * hình), tất cả API trở thành no-op: không import @sentry/react, không network
 * traffic. Khi DSN set, lazy-init ở module load (main.jsx import).
 *
 * Tách wrapper khỏi @sentry/react direct usage để:
 *   - Component code (ErrorBoundary) không phụ thuộc presence của SDK.
 *   - Future swap (Bugsnag / Rollbar) chỉ đổi file này.
 *   - Test/CI không cần Sentry DSN.
 */

const DSN = import.meta.env.VITE_SENTRY_DSN ?? "";
const ENV = import.meta.env.VITE_SENTRY_ENV ?? import.meta.env.MODE ?? "development";

/** @type {typeof import("@sentry/react") | null} */
let sentry = null;

if (DSN) {
  // Dynamic import — bundler vẫn split chunk, nhưng khi không có DSN thì
  // module @sentry/react không tải về client (chunk hash khác = cache hit).
  import("@sentry/react")
    .then((mod) => {
      mod.init({
        dsn: DSN,
        environment: ENV,
        tracesSampleRate: 0,
        replaysSessionSampleRate: 0,
        replaysOnErrorSampleRate: 0,
      });
      sentry = mod;
    })
    .catch(() => {
      // SDK load fail (network / CDN block) — silent, không spam user.
    });
}

/**
 * @param {unknown} err
 * @param {Record<string, unknown>} [context]
 */
export function captureException(err, context) {
  if (!sentry) return;
  sentry.captureException(err, context ? { extra: context } : undefined);
}
