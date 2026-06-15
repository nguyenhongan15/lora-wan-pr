// @ts-check
// Filter "Cộng đồng / Của tôi" — gửi vào /survey/training
// qua param ?contributor=community|me.
//
// Plan-auth-v1 §9.2: chuỗi symbolic được edge/filters.py (resolver duy
// nhất) parse + authorize. UI chỉ chịu trách nhiệm hiển thị + emit value.

import { useId } from "react";
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
  const isLoggedIn = Boolean(user);

  const mode = value === "me" ? "me" : "community";

  /** @param {"community" | "me"} next */
  function selectMode(next) {
    onChange(next);
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
    </fieldset>
  );
}
