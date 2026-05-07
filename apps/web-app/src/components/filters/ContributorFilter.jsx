// @ts-check
// Filter "Cộng đồng / Của tôi / Người dùng cụ thể" — gửi vào /survey/training
// qua param ?contributor=community|me|user/<uuid>.
//
// Plan-auth-v1 §9.2: chuỗi symbolic này được edge/filters.py (resolver duy
// nhất) parse + authorize. UI chỉ chịu trách nhiệm hiển thị + emit value;
// KHÔNG tự assert quyền (vd ẩn "user/" với non-admin). User non-admin chọn
// "user" mà gửi → backend trả 403 admin_required, frontend chỉ hiển thị
// disabled trên radio. Defense-in-depth chứ không phải auth UI-side.

import { useId, useState } from "react";
import { strings } from "../../strings.js";

const t = strings.coverageMap.filters;

/** @typedef {import("../../api/client.js").ContributorMode} ContributorMode */

/**
 * @param {{
 *   value: ContributorMode,
 *   onChange: (next: ContributorMode) => void,
 *   user: import("../../auth/store.js").UserT | null,
 * }} props
 */
export function ContributorFilter({ value, onChange, user }) {
  const groupId = useId();
  const isAdmin = Boolean(user?.is_admin);
  const isLoggedIn = Boolean(user);

  // mode: "community" | "me" | "user"
  // userIdInput: UUID nhập tay khi chọn "user" (admin only).
  const mode = value === "community" ? "community" : value === "me" ? "me" : "user";
  const initialUuid = value.startsWith("user/") ? value.slice(5) : "";
  const [userIdInput, setUserIdInput] = useState(initialUuid);

  /** @param {"community" | "me" | "user"} next */
  function selectMode(next) {
    if (next === "community") onChange("community");
    else if (next === "me") onChange("me");
    else if (userIdInput) onChange(/** @type {ContributorMode} */ (`user/${userIdInput}`));
    else onChange("community"); // user mode chưa có UUID → fallback
  }

  /** @param {string} raw */
  function onUuidChange(raw) {
    setUserIdInput(raw);
    if (mode === "user" && raw) onChange(/** @type {ContributorMode} */ (`user/${raw}`));
  }

  return (
    <fieldset className="space-y-1.5">
      <legend className="text-xs font-semibold text-slate-700">{t.contributor.legend}</legend>

      <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
        <input
          type="radio"
          name={groupId}
          value="community"
          checked={mode === "community"}
          onChange={() => selectMode("community")}
          className="h-3.5 w-3.5"
        />
        <span>{t.contributor.community}</span>
      </label>

      <label
        className={
          "flex items-center gap-1.5 text-xs " +
          (isLoggedIn
            ? "cursor-pointer text-slate-700"
            : "cursor-not-allowed text-slate-400")
        }
        title={isLoggedIn ? undefined : t.contributor.meLoggedOutHint}
      >
        <input
          type="radio"
          name={groupId}
          value="me"
          checked={mode === "me"}
          disabled={!isLoggedIn}
          onChange={() => selectMode("me")}
          className="h-3.5 w-3.5"
        />
        <span>{t.contributor.me}</span>
      </label>

      {isAdmin && (
        <>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-700">
            <input
              type="radio"
              name={groupId}
              value="user"
              checked={mode === "user"}
              onChange={() => selectMode("user")}
              className="h-3.5 w-3.5"
            />
            <span>{t.contributor.user}</span>
          </label>

          {mode === "user" && (
            <input
              type="text"
              placeholder={t.contributor.userIdPlaceholder}
              value={userIdInput}
              onChange={(e) => onUuidChange(e.target.value.trim())}
              className="ml-5 w-full rounded-md border border-slate-300 px-2 py-1 font-mono text-[11px] shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500"
              spellCheck={false}
            />
          )}
        </>
      )}
    </fieldset>
  );
}
