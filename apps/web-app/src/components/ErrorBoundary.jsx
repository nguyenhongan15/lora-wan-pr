// @ts-check
import { Component } from "react";
import { captureException } from "../observability/sentry.js";
import { strings } from "../strings.js";

/**
 * Top-level error boundary — bắt render error trong React tree, hiển thị
 * fallback UI thay vì white-screen. Báo lỗi lên Sentry (no-op nếu DSN không
 * config). Reload button = soft recovery; nếu user reload mà còn lỗi → cùng
 * fallback, user thấy ngay không phải debug.
 *
 * @extends {Component<{ children: import("react").ReactNode }, { hasError: boolean }>}
 */
export class ErrorBoundary extends Component {
  /** @param {{ children: import("react").ReactNode }} props */
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  /** @param {unknown} _error */
  static getDerivedStateFromError(_error) {
    return { hasError: true };
  }

  /**
   * @param {Error} error
   * @param {import("react").ErrorInfo} info
   */
  componentDidCatch(error, info) {
    captureException(error, { componentStack: info.componentStack });
  }

  render() {
    if (this.state.hasError) {
      const t = strings.app.errorBoundary;
      return (
        <div className="flex h-dvh flex-col items-center justify-center bg-slate-50 px-6">
          <div className="max-w-md text-center">
            <h1 className="text-xl font-bold text-slate-900">{t.title}</h1>
            <p className="mt-2 text-sm text-slate-600">{t.hint}</p>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="mt-4 rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
            >
              {t.reload}
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
