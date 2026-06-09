// @ts-check
// AdminPage — container cho tab "Quản trị". Caller (App.jsx) chỉ render khi
// user.is_admin = true. 401 mid-session (token expire) → authFetch tự clear
// store → App ẩn tab → unmount AdminPage. 403 mid-session (admin bị
// demote) → các query hiển thị error riêng, App vẫn giữ tab cho tới next
// auth event.
//
// Layout: sidebar trái (sticky, ~220px) + content phải. Active section
// quản lý bằng useState — không persist qua reload (chấp nhận, tránh
// thêm URL routing). Mỗi section là 1 component độc lập, render-on-demand
// để tránh fetch song song khi user chưa xem.

import { useState } from "react";

import { AdminGateways } from "../components/AdminGateways.jsx";
import { AdminStatsCard } from "./AdminStatsCard.jsx";
import { AdminUsersTable } from "./AdminUsersTable.jsx";
import { ContributionReviewPanel } from "./ContributionReviewPanel.jsx";
import { CoverageRebuildPanel } from "./CoverageRebuildPanel.jsx";
import { GlobalSyncPanel } from "./GlobalSyncPanel.jsx";
import { strings } from "../strings.js";

const t = strings.admin.page;

/** @typedef {"stats" | "review" | "users" | "gateways" | "sync" | "rebuild"} Section */

/** @type {{ key: Section, label: string, heading: string }[]} */
const SECTIONS = [
  { key: "stats", label: t.sidebar.stats, heading: t.statsHeading },
  { key: "review", label: t.sidebar.review, heading: t.reviewHeading },
  { key: "users", label: t.sidebar.users, heading: t.usersHeading },
  { key: "gateways", label: t.sidebar.gateways, heading: t.gatewaysHeading },
  { key: "sync", label: t.sidebar.sync, heading: t.syncHeading },
  { key: "rebuild", label: t.sidebar.rebuild, heading: t.rebuildHeading },
];

/**
 * @param {{ currentUserId: string, currentUserIsSuperAdmin: boolean }} props
 */
export function AdminPage({ currentUserId, currentUserIsSuperAdmin }) {
  const [active, setActive] = useState(/** @type {Section} */ ("stats"));
  const current = SECTIONS.find((s) => s.key === active) ?? SECTIONS[0];

  return (
    <div className="flex h-full">
      <aside className="sticky top-0 h-full w-56 shrink-0 border-r border-slate-200 bg-slate-50">
        <div className="border-b border-slate-200 px-4 py-4">
          <h1 className="text-sm font-bold text-slate-900">{t.title}</h1>
          <p className="mt-1 text-xs text-slate-600">{t.subtitle}</p>
        </div>
        <nav className="flex flex-col p-2">
          {SECTIONS.map((s) => (
            <button
              key={s.key}
              onClick={() => setActive(s.key)}
              className={
                "rounded-md px-3 py-2 text-left text-sm transition " +
                (active === s.key
                  ? "bg-slate-900 font-medium text-white"
                  : "text-slate-700 hover:bg-slate-200")
              }
            >
              {s.label}
            </button>
          ))}
        </nav>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <div className="border-b border-slate-200 bg-white px-6 py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {current.heading}
          </h2>
        </div>
        <div className="p-6">
          {active === "stats" && <AdminStatsCard />}
          {active === "review" && <ContributionReviewPanel />}
          {active === "users" && (
            <AdminUsersTable
              currentUserId={currentUserId}
              canManageAdmin={currentUserIsSuperAdmin}
            />
          )}
          {active === "gateways" && <AdminGateways editable />}
          {active === "sync" && <GlobalSyncPanel />}
          {active === "rebuild" && <CoverageRebuildPanel />}
        </div>
      </main>
    </div>
  );
}
