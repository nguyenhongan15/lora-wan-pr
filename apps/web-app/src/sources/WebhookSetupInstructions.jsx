// @ts-check
// WebhookSetupInstructions — UI hiển thị URL+token webhook 1 lần duy nhất.
//
// Plan ChirpStack per-user webhook ingest §"Show once": backend KHÔNG bao
// giờ trả token lần 2. Component này nhận props (webhookUrl, webhookToken)
// từ caller (AddSourceForm sau link, LinkedSourceCard sau rotate) và hiển
// thị:
//   - Banner cảnh báo show-once (đậm, dễ nhìn)
//   - URL trong text input readonly + nút Copy clipboard
//   - 4-step hướng dẫn paste vào ChirpStack
//   - Nút "Đã copy xong" để dismiss (parent reset state)
//
// KHÔNG persist token vào localStorage/sessionStorage — chỉ giữ trong React
// state của parent (lifetime ≈ session tab). User refresh → state mất → muốn
// xem lại phải rotate.

import { useState } from "react";
import { strings } from "../strings.js";

const t = strings.sources.webhookSetup;

/**
 * @param {{
 *   webhookUrl: string,
 *   webhookToken: string,
 *   onDismiss?: () => void,
 * }} props
 */
export function WebhookSetupInstructions({
  webhookUrl,
  webhookToken,
  onDismiss,
}) {
  const [copied, setCopied] = useState(false);

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(webhookUrl);
      setCopied(true);
      // Reset sau 2s — đủ để user thấy "Đã copy!" mà không kẹt vĩnh viễn.
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API có thể fail (HTTPS-only, không permission). Fallback:
      // select toàn bộ input để user Ctrl+C tay.
      const input = document.getElementById(
        "webhook-url-input",
      );
      if (input instanceof HTMLInputElement) input.select();
    }
  }

  return (
    <section
      role="status"
      className="rounded-lg border-2 border-amber-400 bg-amber-50 p-4 shadow-sm"
    >
      <header className="mb-3">
        <h3 className="text-base font-bold text-amber-900">{t.title}</h3>
        <p className="mt-1 text-sm text-amber-800">{t.subtitle}</p>
      </header>

      <div className="space-y-3">
        <div>
          <label
            htmlFor="webhook-url-input"
            className="block text-xs font-semibold text-amber-900"
          >
            {t.urlLabel}
          </label>
          <div className="mt-1 flex gap-2">
            <input
              id="webhook-url-input"
              type="text"
              value={webhookUrl}
              readOnly
              onClick={(e) => e.currentTarget.select()}
              className="flex-1 rounded-md border border-amber-300 bg-white px-3 py-2 font-mono text-xs text-slate-900"
            />
            <button
              type="button"
              onClick={onCopy}
              className="rounded-md bg-amber-600 px-3 py-2 text-xs font-medium text-white shadow-sm hover:bg-amber-700"
            >
              {copied ? t.copyDone : t.copyBtn}
            </button>
          </div>
        </div>

        <div>
          <label
            htmlFor="webhook-token-input"
            className="block text-xs font-semibold text-amber-900"
          >
            {t.tokenLabel}
          </label>
          <input
            id="webhook-token-input"
            type="text"
            value={webhookToken}
            readOnly
            onClick={(e) => e.currentTarget.select()}
            className="mt-1 w-full rounded-md border border-amber-300 bg-white px-3 py-2 font-mono text-xs text-slate-900"
          />
        </div>

        <div>
          <h4 className="text-sm font-semibold text-amber-900">
            {t.stepsTitle}
          </h4>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-amber-900">
            {t.steps.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>

        {onDismiss && (
          <div className="text-right">
            <button
              type="button"
              onClick={onDismiss}
              className="rounded-md border border-amber-700 px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
            >
              {t.dismissBtn}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
