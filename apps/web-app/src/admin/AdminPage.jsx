// @ts-check
// AdminPage — container cho tab "Quản trị". Caller (App.jsx) chỉ render khi
// user.is_admin = true. 401 mid-session (token expire) → authFetch tự clear
// store → App ẩn tab → unmount AdminPage. 403 mid-session (admin bị
// demote) → các query hiển thị error riêng, App vẫn giữ tab cho tới next
// auth event.
//
// Layout: Stats (top) → Users table (middle) → Global sync panel (bottom).
// Mỗi section là 1 component độc lập với query/mutation riêng — không share
// state.

import { AdminStatsCard } from "./AdminStatsCard.jsx";
import { AdminUsersTable } from "./AdminUsersTable.jsx";
import { ContributionReviewPanel } from "./ContributionReviewPanel.jsx";
import { GlobalSyncPanel } from "./GlobalSyncPanel.jsx";
import { strings } from "../strings.js";

const t = strings.admin.page;

/**
 * @param {{ currentUserId: string }} props
 */
export function AdminPage({ currentUserId }) {
  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header>
        <h1 className="text-xl font-bold text-slate-900">{t.title}</h1>
        <p className="mt-1 text-sm text-slate-600">{t.subtitle}</p>
      </header>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t.statsHeading}
        </h2>
        <AdminStatsCard />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t.reviewHeading}
        </h2>
        <ContributionReviewPanel />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t.usersHeading}
        </h2>
        <AdminUsersTable currentUserId={currentUserId} />
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          {t.syncHeading}
        </h2>
        <GlobalSyncPanel />
      </section>
    </div>
  );
}
