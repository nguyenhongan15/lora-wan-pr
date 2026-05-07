// @ts-check
// Add lpwanmapper source form.
//
// V1 chỉ hỗ trợ source_type="lpwanmapper" — hardcode dropdown 1 option để
// future-proof (Step v2 thêm chirpstack / csv chỉ cần thêm option).
//
// Credential lpwanmapper = {email, password}. Plan §3.2 + adapter.connect
// validate shape. Backend `linking.test()` gọi adapter.connect — sai email/
// password → 400 credential_test_failed (KHÔNG persist).
//
// Privacy: password input dùng autoComplete="off" thay vì "new-password" —
// "new-password" semantic = gợi ý mật khẩu mạnh khi đăng ký, sai context
// (đây là credential bên thứ 3 user đã có sẵn). Sau khi mutation success,
// reset state ngay → password không lingering trong React state.

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { linkSource } from "./client.js";
import { strings } from "../strings.js";

const t = strings.sources.addForm;
const tErr = strings.sources.errors;

export function AddSourceForm() {
  const [label, setLabel] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const qc = useQueryClient();

  const m = useMutation({
    mutationFn: linkSource,
    onSuccess: () => {
      // Clear credential ngay khỏi state — không lingering.
      setLabel("");
      setEmail("");
      setPassword("");
      qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    m.mutate({
      source_type: "lpwanmapper",
      label: label.trim(),
      credentials: { email: email.trim(), password },
    });
  }

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-base font-semibold text-slate-900">{t.title}</h2>
      <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>

      <form onSubmit={onSubmit} className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label
            htmlFor="src-type"
            className="block text-sm font-medium text-slate-700"
          >
            {t.sourceTypeLabel}
          </label>
          <select
            id="src-type"
            value="lpwanmapper"
            disabled
            className="mt-1 w-full rounded-md border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-700 shadow-sm"
          >
            <option value="lpwanmapper">lpwanmapper</option>
          </select>
        </div>

        <div className="sm:col-span-2">
          <label
            htmlFor="src-label"
            className="block text-sm font-medium text-slate-700"
          >
            {t.labelLabel}
          </label>
          <input
            id="src-label"
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder={t.labelPlaceholder}
            required
            maxLength={100}
            autoComplete="off"
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
          />
        </div>

        <div>
          <label
            htmlFor="src-email"
            className="block text-sm font-medium text-slate-700"
          >
            {t.emailLabel}
          </label>
          <input
            id="src-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="off"
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
          />
        </div>

        <div>
          <label
            htmlFor="src-password"
            className="block text-sm font-medium text-slate-700"
          >
            {t.passwordLabel}
          </label>
          <input
            id="src-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="off"
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
          />
        </div>

        <div className="sm:col-span-2">
          <button
            type="submit"
            disabled={m.isPending}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:opacity-50"
          >
            {m.isPending ? t.submitPending : t.submit}
          </button>
        </div>
      </form>

      {m.isSuccess && (
        <div
          role="status"
          className="mt-3 rounded-md border border-green-300 bg-green-50 p-3 text-sm text-green-800"
        >
          {t.successHint}
        </div>
      )}

      {m.isError && <FormError error={m.error} />}
    </section>
  );
}

/** @param {{ error: unknown }} props */
function FormError({ error }) {
  if (error instanceof ApiError) {
    const code = error.problem.code ?? "";
    const localized = tErr.byCode(code);
    const msg = localized || error.problem.detail || error.problem.title;
    return (
      <div
        role="alert"
        className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
      >
        <div className="font-semibold">{msg}</div>
        {code && (
          <div className="mt-1 text-xs text-red-600">
            {tErr.errorCodeLabel}: {code}
          </div>
        )}
      </div>
    );
  }
  return (
    <div
      role="alert"
      className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800"
    >
      {String(error)}
    </div>
  );
}
