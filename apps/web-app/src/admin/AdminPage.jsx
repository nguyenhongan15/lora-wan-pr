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
import { MLRetrainPanel } from "./MLRetrainPanel.jsx";
import { NotificationsPanel } from "./NotificationsPanel.jsx";
import { TrainingBatchesPanel } from "./TrainingBatchesPanel.jsx";
import { strings } from "../strings.js";

const t = strings.admin.page;

/** @typedef {"stats" | "review" | "training" | "users" | "gateways" | "sync" | "rebuild" | "retrain" | "notifications"} Section */

/** @type {{ key: Section, label: string, heading: string }[]} */
const SECTIONS = [
  { key: "stats", label: t.sidebar.stats, heading: t.statsHeading },
  { key: "review", label: t.sidebar.review, heading: t.reviewHeading },
  { key: "training", label: t.sidebar.training, heading: t.trainingHeading },
  { key: "users", label: t.sidebar.users, heading: t.usersHeading },
  { key: "gateways", label: t.sidebar.gateways, heading: t.gatewaysHeading },
  // { key: "sync", label: t.sidebar.sync, heading: t.syncHeading }, // tạm ẩn
  { key: "rebuild", label: t.sidebar.rebuild, heading: t.rebuildHeading },
  { key: "retrain", label: t.sidebar.retrain, heading: t.retrainHeading },
  { key: "notifications", label: t.sidebar.notifications, heading: t.notificationsHeading },
];

/**
 * @param {{ currentUserId: string, currentUserIsSuperAdmin: boolean }} props
 */
export function AdminPage({ currentUserId, currentUserIsSuperAdmin }) {
  const [active, setActive] = useState(/** @type {Section} */ ("stats"));
  const current = SECTIONS.find((s) => s.key === active) ?? SECTIONS[0];

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="shrink-0 border-b border-slate-200 bg-slate-50 md:sticky md:top-0 md:h-full md:w-56 md:border-b-0 md:border-r">
        <div className="border-b border-slate-200 px-4 py-3 md:py-4">
          <h1 className="text-sm font-bold text-slate-900">{t.title}</h1>
          <p className="mt-1 hidden text-xs text-slate-600 md:block">{t.subtitle}</p>
        </div>
        {/* Mobile: nav cuộn ngang (overflow-x-auto + flex-row + shrink-0
            children). Desktop: stack dọc như cũ. `whitespace-nowrap` để label
            section dài không xuống dòng làm height nav lệch. */}
        <nav className="flex flex-row gap-1 overflow-x-auto p-2 md:flex-col md:gap-0">
          {SECTIONS.map((s) => (
            <button
              key={s.key}
              onClick={() => setActive(s.key)}
              className={
                "shrink-0 whitespace-nowrap rounded-md px-3 py-2 text-left text-sm transition md:w-full " +
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

      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="border-b border-slate-200 bg-white px-4 py-3 md:px-6 md:py-4">
          <h2 className="text-base font-semibold text-slate-900">
            {current.heading}
          </h2>
        </div>
        <div className="p-4 md:p-6">
          {active === "stats" && <AdminStatsCard />}
          {active === "review" && <ContributionReviewPanel />}
          {active === "training" && <TrainingBatchesPanel />}
          {active === "users" && (
            <AdminUsersTable
              currentUserId={currentUserId}
              canManageAdmin={currentUserIsSuperAdmin}
            />
          )}
          {active === "gateways" && <AdminGateways editable />}
          {active === "sync" && <GlobalSyncPanel />}
          {active === "rebuild" && <CoverageRebuildPanel />}
          {active === "retrain" && <MLRetrainPanel />}
          {active === "notifications" && <NotificationsPanel />}
        </div>
      </main>
    </div>
  );
}
