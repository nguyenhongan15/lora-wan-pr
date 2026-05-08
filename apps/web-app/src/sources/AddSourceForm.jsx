// @ts-check
// Add source form — chọn loại nguồn rồi nhập credential tương ứng.
//
// Source types match backend registry (sources/__init__.py): "lpwanmapper",
// "chirpstack". Credential shape khác nhau giữa adapter — switch fields
// theo state.sourceType. Backend `linking.test()` gọi adapter.connect ⇒ sai
// → 400 credential_test_failed (KHÔNG persist).
//
// Privacy: password/api_token dùng autoComplete="off" — đây là credential
// bên thứ 3 user đã có sẵn, không phải tạo mới. Reset state ngay sau success
// hoặc khi đổi loại nguồn → không lingering.

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../auth/client.js";
import { linkSource } from "./client.js";
import { strings } from "../strings.js";

const t = strings.sources.addForm;
const tErr = strings.sources.errors;

/** @typedef {"lpwanmapper" | "chirpstack"} SourceType */

/**
 * Union shape — chứa toàn bộ field của mọi adapter. Tùy `sourceType` mà
 * onSubmit chỉ pick subset tương ứng. Khai báo type tường minh để TS
 * không suy ra literal `""` từ Object.freeze bên dưới (nếu để TS tự suy,
 * setCreds(c => ({ ...c, email: v })) sẽ fail vì `string` ≠ `""`).
 *
 * @typedef {{
 *   email: string,
 *   password: string,
 *   api_url: string,
 *   api_token: string,
 *   tenant_id: string,
 * }} Creds
 */

/** @type {Readonly<Creds>} */
const EMPTY_CREDS = Object.freeze({
  email: "",
  password: "",
  api_url: "",
  api_token: "",
  tenant_id: "",
});

export function AddSourceForm() {
  const [sourceType, setSourceType] = useState(
    /** @type {SourceType} */ ("lpwanmapper"),
  );
  const [label, setLabel] = useState("");
  const [creds, setCreds] = useState(
    /** @type {Creds} */ ({ ...EMPTY_CREDS }),
  );
  const qc = useQueryClient();

  const m = useMutation({
    mutationFn: linkSource,
    onSuccess: () => {
      // Clear credential ngay khỏi state — không lingering.
      setLabel("");
      setCreds({ ...EMPTY_CREDS });
      qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  /** @param {SourceType} next */
  function onChangeSourceType(next) {
    if (next === sourceType) return;
    setSourceType(next);
    // Đổi adapter = đổi shape credential → reset để tránh nhầm field cũ.
    setCreds({ ...EMPTY_CREDS });
    m.reset();
  }

  /** @param {import("react").FormEvent} e */
  function onSubmit(e) {
    e.preventDefault();
    /** @type {Record<string, string>} */
    let credentials;
    if (sourceType === "lpwanmapper") {
      credentials = {
        email: creds.email.trim(),
        password: creds.password,
      };
    } else {
      credentials = {
        api_url: creds.api_url.trim(),
        api_token: creds.api_token.trim(),
      };
      const tenant = creds.tenant_id.trim();
      if (tenant) credentials.tenant_id = tenant;
    }
    m.mutate({
      source_type: sourceType,
      label: label.trim(),
      credentials,
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
            value={sourceType}
            onChange={(e) =>
              onChangeSourceType(/** @type {SourceType} */ (e.target.value))
            }
            className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
          >
            <option value="lpwanmapper">lpwanmapper</option>
            <option value="chirpstack">chirpstack</option>
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

        {sourceType === "lpwanmapper" ? (
          <LpwanmapperFields
            email={creds.email}
            password={creds.password}
            onChangeEmail={(v) => setCreds((c) => ({ ...c, email: v }))}
            onChangePassword={(v) => setCreds((c) => ({ ...c, password: v }))}
          />
        ) : (
          <ChirpStackFields
            apiUrl={creds.api_url}
            apiToken={creds.api_token}
            tenantId={creds.tenant_id}
            onChangeApiUrl={(v) => setCreds((c) => ({ ...c, api_url: v }))}
            onChangeApiToken={(v) =>
              setCreds((c) => ({ ...c, api_token: v }))
            }
            onChangeTenantId={(v) =>
              setCreds((c) => ({ ...c, tenant_id: v }))
            }
          />
        )}

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

/**
 * @param {{
 *   email: string,
 *   password: string,
 *   onChangeEmail: (v: string) => void,
 *   onChangePassword: (v: string) => void,
 * }} props
 */
function LpwanmapperFields({
  email,
  password,
  onChangeEmail,
  onChangePassword,
}) {
  const tt = t.lpwanmapper;
  return (
    <>
      <div>
        <label
          htmlFor="src-email"
          className="block text-sm font-medium text-slate-700"
        >
          {tt.emailLabel}
        </label>
        <input
          id="src-email"
          type="email"
          value={email}
          onChange={(e) => onChangeEmail(e.target.value)}
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
          {tt.passwordLabel}
        </label>
        <input
          id="src-password"
          type="password"
          value={password}
          onChange={(e) => onChangePassword(e.target.value)}
          required
          autoComplete="off"
          className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
        />
      </div>
    </>
  );
}

/**
 * @param {{
 *   apiUrl: string,
 *   apiToken: string,
 *   tenantId: string,
 *   onChangeApiUrl: (v: string) => void,
 *   onChangeApiToken: (v: string) => void,
 *   onChangeTenantId: (v: string) => void,
 * }} props
 */
function ChirpStackFields({
  apiUrl,
  apiToken,
  tenantId,
  onChangeApiUrl,
  onChangeApiToken,
  onChangeTenantId,
}) {
  const tt = t.chirpstack;
  return (
    <>
      <div className="sm:col-span-2">
        <label
          htmlFor="src-cs-url"
          className="block text-sm font-medium text-slate-700"
        >
          {tt.apiUrlLabel}
        </label>
        <input
          id="src-cs-url"
          type="url"
          value={apiUrl}
          onChange={(e) => onChangeApiUrl(e.target.value)}
          placeholder={tt.apiUrlPlaceholder}
          required
          autoComplete="off"
          className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
        />
      </div>

      <div className="sm:col-span-2">
        <label
          htmlFor="src-cs-token"
          className="block text-sm font-medium text-slate-700"
        >
          {tt.apiTokenLabel}
        </label>
        <input
          id="src-cs-token"
          type="password"
          value={apiToken}
          onChange={(e) => onChangeApiToken(e.target.value)}
          required
          autoComplete="off"
          className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
        />
        <p className="mt-1 text-xs text-slate-500">{tt.apiTokenHint}</p>
      </div>

      <div className="sm:col-span-2">
        <label
          htmlFor="src-cs-tenant"
          className="block text-sm font-medium text-slate-700"
        >
          {tt.tenantIdLabel}
        </label>
        <input
          id="src-cs-tenant"
          type="text"
          value={tenantId}
          onChange={(e) => onChangeTenantId(e.target.value)}
          autoComplete="off"
          className="mt-1 w-full rounded-md border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:ring-slate-500"
        />
        <p className="mt-1 text-xs text-slate-500">{tt.tenantIdHint}</p>
      </div>
    </>
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