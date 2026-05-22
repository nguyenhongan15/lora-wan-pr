// @ts-check
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { AdminGateways } from "./components/AdminGateways.jsx";
import { AdminPage } from "./admin/AdminPage.jsx";
import { BulkLookup } from "./components/BulkLookup.jsx";
import { CoverageMap } from "./components/CoverageMap.jsx";
import { AuthModal } from "./auth/AuthModal.jsx";
import { ResetPassword } from "./auth/ResetPassword.jsx";
import { getUser, subscribe } from "./auth/store.js";
import { bootstrap, logout } from "./auth/client.js";
import { SourcesPage } from "./sources/SourcesPage.jsx";
import { strings } from "./strings.js";

/** @typedef {"predict" | "map" | "heatmap" | "bulk" | "admin" | "sources" | "adminPanel"} Tab */

/**
 * Đọc `?reset=<token>` từ URL ở thời điểm App mount. Không subscribe — token
 * chỉ cần một lần để render ResetPassword. Sau khi user click "Đăng nhập"
 * (onDone), App push history mới và bỏ qua query.
 *
 * Trả empty-string nếu URL có `?reset=` nhưng giá trị rỗng → ResetPassword
 * render fallback "Link không hợp lệ". Trả `null` nếu không có param.
 */
function _readResetTokenFromUrl() {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  if (!params.has("reset")) return null;
  return params.get("reset") ?? "";
}

export function App() {
  const [tab, setTab] = useState(/** @type {Tab} */ ("map"));
  const [authOpen, setAuthOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [resetToken, setResetToken] = useState(_readResetTokenFromUrl);
  // Handoff state cho luồng Bulk → Predict: BulkLookup gọi onViewOnMap với
  // danh sách điểm đã predict; App lưu vào ref-state, chuyển tab, và truyền
  // xuống CoverageMap (mode="predict"). Sau khi CoverageMap consume xong,
  // gọi onConsumed → null state để không render lại nếu user navigate qua lại.
  const [bulkHandoff, setBulkHandoff] = useState(
    /** @type {import("./components/BulkLookup.jsx").BulkHandoffPoint[] | null} */ (
      null
    ),
  );
  // useCallback giữ identity stable qua các App render không liên quan
  // (auth bootstrap, menu toggle, …). Nếu callback đổi ref, CoverageMap effect
  // dep `onBulkHandoffConsumed` sẽ trigger lại trong khi bulkHandoff vẫn còn,
  // gây flicker / fitBounds chạy 2 lần.
  const handleViewBulkOnMap = useCallback(
    /** @param {import("./components/BulkLookup.jsx").BulkHandoffPoint[]} points */
    (points) => {
      setBulkHandoff(points);
      setTab("predict");
    },
    [],
  );
  const handleBulkHandoffConsumed = useCallback(() => setBulkHandoff(null), []);
  const user = useSyncExternalStore(subscribe, getUser);
  const t = strings.app;
  const tHeader = strings.auth.header;

  // App mount → rehydrate session từ HttpOnly cookie (auth v2). Nếu cookie
  // còn valid, POST /auth/refresh + GET /me restore in-memory token + user.
  // Cookie hết hạn / bị revoke → bootstrap trả null, user vẫn logged-out.
  //
  // Skip bootstrap khi đang ở reset flow — user vào từ email, không nên có
  // session sẵn (đặt lại pass = re-login). Backend cũng sẽ revoke session
  // sau confirm; bootstrap chạy lúc đó sẽ no-op vì cookie đã invalid.
  useEffect(() => {
    if (resetToken !== null) return;
    bootstrap().catch(() => {
      // Lỗi mạng / parse: coi như chưa login, không show banner — silent.
    });
  }, [resetToken]);

  // Tab "sources" cần user. Tab "adminPanel" cần user.is_admin.
  // Khi điều kiện không còn (logout / token expire / admin bị demote giữa
  // session) mà đang ở tab đó → switch về "map" để tránh render component
  // không có quyền (sẽ 401/403 và hiện error vô ích).
  useEffect(() => {
    if (!user && tab === "sources") setTab("map");
    if (!user?.is_admin && tab === "adminPanel") setTab("map");
  }, [user, tab]);

  // Reset mode: render full-screen, không render app chính. Sau khi user xong
  // (success → click "Đăng nhập" hoặc cancel) → clear param + state, mở
  // AuthModal login. Đặt SAU mọi useState/useEffect để không vi phạm
  // rules-of-hooks (early-return phải sau hooks).
  if (resetToken !== null) {
    return (
      <ResetPassword
        token={resetToken || null}
        onDone={() => {
          // Clear `?reset=` khỏi URL mà không reload (replaceState giữ history).
          if (typeof window !== "undefined") {
            window.history.replaceState({}, "", window.location.pathname);
          }
          setResetToken(null);
          setAuthOpen(true);
        }}
      />
    );
  }

  function onAvatarClick() {
    if (user) setMenuOpen((o) => !o);
    else setAuthOpen(true);
  }

  async function onLogout() {
    setMenuOpen(false);
    await logout();
  }

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-4 px-6 py-3">
          <div>
            <h1 className="text-lg font-bold text-slate-900">{t.title}</h1>

          </div>
          <div className="flex items-center gap-3">
            <nav className="flex gap-2">
              <TabButton active={tab === "map"} onClick={() => setTab("map")}>
                {t.tabs.map}
              </TabButton>
              <TabButton active={tab === "heatmap"} onClick={() => setTab("heatmap")}>
                {t.tabs.heatmap}
              </TabButton>

              <TabButton active={tab === "predict"} onClick={() => setTab("predict")}>
                {t.tabs.predict}
              </TabButton>
              <TabButton active={tab === "bulk"} onClick={() => setTab("bulk")}>
                {t.tabs.bulk}
              </TabButton>
              <TabButton active={tab === "admin"} onClick={() => setTab("admin")}>
                {t.tabs.admin}
              </TabButton>
              {user && (
                <TabButton
                  active={tab === "sources"}
                  onClick={() => setTab("sources")}
                >
                  {t.tabs.sources}
                </TabButton>
              )}
              {user?.is_admin && (
                <TabButton
                  active={tab === "adminPanel"}
                  onClick={() => setTab("adminPanel")}
                >
                  {t.tabs.adminPanel}
                </TabButton>
              )}
            </nav>
            <div className="relative">
            <button
              type="button"
              onClick={onAvatarClick}
              aria-label={user ? tHeader.avatarLoggedIn : tHeader.avatarLoggedOut}
              aria-haspopup={user ? "menu" : "dialog"}
              aria-expanded={user ? menuOpen : authOpen}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-slate-300 bg-slate-100 text-sm font-semibold text-slate-700 hover:bg-slate-200"
            >
              {user ? user.email[0].toUpperCase() : <UserIcon />}
            </button>

            {user && menuOpen && (
              <>
                {/* click-catcher để đóng menu khi click ra ngoài */}
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setMenuOpen(false)}
                  aria-hidden="true"
                />
                <div
                  role="menu"
                  className="absolute right-0 top-full z-50 mt-2 w-64 rounded-md border border-slate-200 bg-white p-3 shadow-lg"
                >
                  <div className="break-all text-sm font-medium text-slate-900">
                    {user.email}
                  </div>
                  {user.is_admin && (
                    <span className="mt-1 inline-block rounded bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                      {tHeader.adminBadge}
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={onLogout}
                    className="mt-3 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
                  >
                    {tHeader.logout}
                  </button>
                </div>
              </>
            )}
            </div>
          </div>
        </div>
      </header>

      <main className="min-h-0 flex-1">
        {tab === "map" && <CoverageMap mode="points" />}
        {tab === "heatmap" && <CoverageMap mode="heatmap" />}
        {tab === "predict" && (
          <CoverageMap
            mode="predict"
            bulkHandoff={bulkHandoff}
            onBulkHandoffConsumed={handleBulkHandoffConsumed}
          />
        )}
        {/* Bulk tab luôn mount để state (csvText, kết quả mutation, sf) sống
            sót khi user "Xem trên bản đồ" → quay lại tab Tra cứu hàng loạt.
            Display:none giữ instance React + DOM. */}
        <div className={tab === "bulk" ? "h-full overflow-y-auto" : "hidden"}>
          <BulkLookup onViewOnMap={handleViewBulkOnMap} />
        </div>
        {tab === "admin" && (
          <div className="h-full overflow-y-auto">
            <AdminGateways />
          </div>
        )}
        {tab === "sources" && user && (
          <div className="h-full overflow-y-auto">
            <SourcesPage />
          </div>
        )}
        {tab === "adminPanel" && user?.is_admin && (
          <div className="h-full overflow-y-auto">
            <AdminPage currentUserId={user.id} />
          </div>
        )}
      </main>

      <AuthModal isOpen={authOpen} onClose={() => setAuthOpen(false)} />
    </div>
  );
}

/**
 * @param {{ active: boolean, onClick: () => void, children: import("react").ReactNode }} props
 */
function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-md px-3 py-1.5 text-sm font-medium transition " +
        (active
          ? "bg-slate-900 text-white"
          : "border border-slate-300 text-slate-700 hover:bg-slate-100")
      }
    >
      {children}
    </button>
  );
}

function UserIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="currentColor"
      className="h-5 w-5"
      aria-hidden="true"
    >
      <path d="M12 12a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9Zm-7 8.25a7 7 0 0 1 14 0 .75.75 0 0 1-.75.75H5.75a.75.75 0 0 1-.75-.75Z" />
    </svg>
  );
}
