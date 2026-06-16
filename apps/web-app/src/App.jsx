// @ts-check
import { useEffect, useState, useSyncExternalStore } from "react";
import { AdminGateways } from "./components/AdminGateways.jsx";
import { AdminPage } from "./admin/AdminPage.jsx";
import { CoverageMap } from "./components/CoverageMap.jsx";
import { LandingPage } from "./components/LandingPage.jsx";
import { AuthModal } from "./auth/AuthModal.jsx";
import { EmailVerifyConfirmPage } from "./auth/EmailVerifyConfirmPage.jsx";
import { EmailVerifyModal } from "./auth/EmailVerifyModal.jsx";
import { ResetPassword } from "./auth/ResetPassword.jsx";
import { getUser, subscribe } from "./auth/store.js";
import { bootstrap, logout } from "./auth/client.js";
import { SourcesPage } from "./sources/SourcesPage.jsx";
import { strings } from "./strings.js";

/** @typedef {"home" | "predict" | "map" | "heatmap" | "admin" | "sources" | "adminPanel"} Tab */

/** @type {ReadonlySet<Tab>} */
const _VALID_TABS = new Set(/** @type {Tab[]} */ ([
  "home",
  "predict",
  "map",
  "heatmap",
  "admin",
  "sources",
  "adminPanel",
]));

/** Đọc `page=X` từ hash → trả tab id; fallback "home" nếu thiếu/sai. */
function _readPageFromHash() {
  if (typeof window === "undefined") return /** @type {Tab} */ ("home");
  const raw = window.location.hash.replace(/^#/, "");
  const params = new URLSearchParams(raw);
  const p = params.get("page");
  return p && _VALID_TABS.has(/** @type {Tab} */ (p))
    ? /** @type {Tab} */ (p)
    : /** @type {Tab} */ ("home");
}

/**
 * Ghi `page=` vào hash (replaceState — không spam history). Tab "home" = clear hash.
 * `subTab` optional → `#page=sources&tab=manage` cho SourcesPage sub-section.
 * @param {Tab} next
 * @param {string} [subTab]
 */
function _writePageToHash(next, subTab) {
  if (typeof window === "undefined") return;
  // Giữ nguyên `?...` để filter URL state (contributor, linked_source, source)
  // sống qua đổi tab. Nếu wipe search, "qua trang chủ rồi quay lại map" sẽ
  // mất contributor=me → me/user effect wipe phiên realtime đã restore.
  const base = `${window.location.pathname}${window.location.search}`;
  if (next === "home") {
    window.history.replaceState(null, "", base);
  } else if (subTab) {
    window.history.replaceState(null, "", `${base}#page=${next}&tab=${subTab}`);
  } else {
    window.history.replaceState(null, "", `${base}#page=${next}`);
  }
}

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

/**
 * Đọc `?verify_email=<token>` cho luồng xác thực email (mirror reset). Trả
 * empty-string nếu param có nhưng giá trị rỗng → page render fallback.
 */
function _readVerifyEmailTokenFromUrl() {
  if (typeof window === "undefined") return null;
  const params = new URLSearchParams(window.location.search);
  if (!params.has("verify_email")) return null;
  return params.get("verify_email") ?? "";
}

/**
 * SPA hiện chỉ phục vụ ở "/" — mọi pathname khác là 404. Nginx phải fallback
 * mọi route về index.html (single bundle) nên kiểm tra ở client-side.
 */
function _isUnknownPath() {
  if (typeof window === "undefined") return false;
  return window.location.pathname !== "/" && window.location.pathname !== "";
}

export function App() {
  const [tab, setTab] = useState(_readPageFromHash);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [authOpen, setAuthOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [navMenuOpen, setNavMenuOpen] = useState(false);
  const [verifyOpen, setVerifyOpen] = useState(false);
  const [resetToken, setResetToken] = useState(_readResetTokenFromUrl);
  const [verifyEmailToken, setVerifyEmailToken] = useState(
    _readVerifyEmailTokenFromUrl,
  );
  const [postLoginAction, setPostLoginAction] = useState(
    /** @type {{ run: () => void } | null} */ (null),
  );
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
  //
  // Verify-email flow KHÔNG cần effect riêng: bootstrap idempotent
  // (`if (getToken()) return null`), chạy 2 lần song song race trên
  // /auth/refresh → refresh-family revoke. EmailVerifyConfirmPage tự refresh
  // user payload sau khi mutation isSuccess (effect riêng trong page đó).
  useEffect(() => {
    if (resetToken !== null) {
      setBootstrapped(true);
      return;
    }
    bootstrap()
      .catch(() => {
        // Lỗi mạng / parse: coi như chưa login, không show banner — silent.
      })
      .finally(() => setBootstrapped(true));
  }, [resetToken]);

  // Sync back/forward navigation: browser back → hashchange → set tab khớp.
  useEffect(() => {
    function onHashChange() {
      setTab(_readPageFromHash());
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // Pageview beacon cho admin dashboard "Tổng quan". Fire-and-forget mỗi mount
  // (mỗi reload / mỗi tab mở = +1). Endpoint public, không auth, không trả body.
  useEffect(() => {
    const base =
      typeof window !== "undefined" &&
      (window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1")
        ? "http://localhost:8000"
        : import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
    fetch(`${base}/api/v1/telemetry/visit`, { method: "POST" }).catch(() => {
      // Ngầm bỏ qua lỗi mạng — chart admin tự reconcile lần sau, không phá UX.
    });
  }, []);

  // Landing CTA "Mở Dữ liệu của tôi" / "Đóng góp dữ liệu" → mở AuthModal khi chưa
  // login, đăng nhập xong tự navigate. Effect fire khi user becomes truthy.
  useEffect(() => {
    if (!user || !postLoginAction) return;
    postLoginAction.run();
    setPostLoginAction(null);
  }, [user, postLoginAction]);

  // Tab "sources" cần user. Tab "adminPanel" cần user.is_admin.
  // Khi điều kiện không còn (logout / token expire / admin bị demote giữa
  // session) mà đang ở tab đó → switch về "home" để tránh render component
  // không có quyền (sẽ 401/403 và hiện error vô ích).
  //
  // Guard chỉ chạy SAU khi bootstrap settled — tránh race condition: refresh
  // với hash `#page=sources`, lúc mount user=null → guard reset "home" TRƯỚC
  // khi bootstrap khôi phục user → mất tab.
  useEffect(() => {
    if (!bootstrapped) return;
    if (!user && tab === "sources") {
      setTab("home");
      _writePageToHash("home");
    }
    if (!user?.is_admin && tab === "adminPanel") {
      setTab("home");
      _writePageToHash("home");
    }
  }, [bootstrapped, user, tab]);

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

  if (verifyEmailToken !== null) {
    return (
      <EmailVerifyConfirmPage
        token={verifyEmailToken || null}
        onDone={() => {
          if (typeof window !== "undefined") {
            window.history.replaceState({}, "", window.location.pathname);
          }
          setVerifyEmailToken(null);
        }}
      />
    );
  }

  if (_isUnknownPath()) {
    return <NotFoundPage />;
  }

  function onAvatarClick() {
    if (user) setMenuOpen((o) => !o);
    else setAuthOpen(true);
  }

  async function onLogout() {
    setMenuOpen(false);
    await logout();
  }

  /**
   * Chọn tab + đóng nav menu mobile (nếu đang mở). Dùng cho cả desktop nav
   * và mobile dropdown để không phải lặp `setNavMenuOpen(false)` ở mỗi callback.
   * Ghi hash → refresh giữ nguyên tab. `subTab` optional cho SourcesPage.
   * @param {Tab} next
   * @param {string} [subTab]
   */
  function selectTab(next, subTab) {
    setTab(next);
    _writePageToHash(next, subTab);
    setNavMenuOpen(false);
  }

  /**
   * Mở AuthModal; nếu caller cung cấp afterLogin → lưu để fire sau khi đăng nhập
   * thành công. User đóng modal mà không login → drop pending action.
   * @param {(() => void) | undefined} [afterLogin]
   */
  function requestLogin(afterLogin) {
    setPostLoginAction(afterLogin ? { run: afterLogin } : null);
    setAuthOpen(true);
  }

  function closeAuthModal() {
    setAuthOpen(false);
    if (!getUser()) setPostLoginAction(null);
  }

  return (
    <div className="flex h-dvh flex-col">
      <header className="shrink-0 border-b border-slate-200 bg-white">
        <div className="flex items-center justify-between gap-3 px-4 py-3 md:gap-4 md:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-base font-bold text-slate-900 md:text-lg">{t.title}</h1>

          </div>
          <div className="flex items-center gap-2 md:gap-3">
            <nav className="hidden gap-2 md:flex">
              <TabButton active={tab === "home"} onClick={() => selectTab("home")}>
                {t.tabs.home}
              </TabButton>
              <TabButton active={tab === "map"} onClick={() => selectTab("map")}>
                {t.tabs.map}
              </TabButton>
              <TabButton active={tab === "heatmap"} onClick={() => selectTab("heatmap")}>
                {t.tabs.heatmap}
              </TabButton>

              <TabButton active={tab === "predict"} onClick={() => selectTab("predict")}>
                {t.tabs.predict}
              </TabButton>
              <TabButton active={tab === "admin"} onClick={() => selectTab("admin")}>
                {t.tabs.admin}
              </TabButton>
              {user && (
                <TabButton
                  active={tab === "sources"}
                  onClick={() => selectTab("sources")}
                >
                  {t.tabs.sources}
                </TabButton>
              )}
              {user?.is_admin && (
                <TabButton
                  active={tab === "adminPanel"}
                  onClick={() => selectTab("adminPanel")}
                >
                  {t.tabs.adminPanel}
                </TabButton>
              )}
            </nav>
            <button
              type="button"
              onClick={() => setNavMenuOpen((o) => !o)}
              aria-label={navMenuOpen ? t.navMenu.close : t.navMenu.open}
              aria-expanded={navMenuOpen}
              aria-controls="mobile-nav-menu"
              className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-300 bg-white text-slate-700 hover:bg-slate-100 md:hidden"
            >
              {navMenuOpen ? <CloseIcon /> : <HamburgerIcon />}
            </button>
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
                  {user.email_verified ? (
                    <div className="mt-2 inline-flex items-center gap-1 rounded bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        viewBox="0 0 20 20"
                        fill="currentColor"
                        className="h-3.5 w-3.5"
                        aria-hidden="true"
                      >
                        <path
                          fillRule="evenodd"
                          d="M16.704 5.29a1 1 0 0 1 .006 1.414l-7.5 7.55a1 1 0 0 1-1.42 0L3.29 9.755a1 1 0 1 1 1.42-1.41l3.79 3.81 6.79-6.86a1 1 0 0 1 1.414-.005Z"
                          clipRule="evenodd"
                        />
                      </svg>
                      {tHeader.verifiedBadge}
                    </div>
                  ) : (
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        setVerifyOpen(true);
                      }}
                      className="mt-2 w-full rounded-md border border-sky-300 bg-sky-50 px-3 py-1.5 text-sm font-medium text-sky-800 hover:bg-sky-100"
                    >
                      {tHeader.verifyEmailButton}
                    </button>
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
        {navMenuOpen && (
          <nav
            id="mobile-nav-menu"
            className="flex flex-col gap-1.5 border-t border-slate-200 bg-white px-4 py-3 md:hidden"
          >
            <TabButton fullWidth active={tab === "home"} onClick={() => selectTab("home")}>
              {t.tabs.home}
            </TabButton>
            <TabButton fullWidth active={tab === "map"} onClick={() => selectTab("map")}>
              {t.tabs.map}
            </TabButton>
            <TabButton fullWidth active={tab === "heatmap"} onClick={() => selectTab("heatmap")}>
              {t.tabs.heatmap}
            </TabButton>
            <TabButton fullWidth active={tab === "predict"} onClick={() => selectTab("predict")}>
              {t.tabs.predict}
            </TabButton>
            <TabButton fullWidth active={tab === "admin"} onClick={() => selectTab("admin")}>
              {t.tabs.admin}
            </TabButton>
            {user && (
              <TabButton fullWidth active={tab === "sources"} onClick={() => selectTab("sources")}>
                {t.tabs.sources}
              </TabButton>
            )}
            {user?.is_admin && (
              <TabButton fullWidth active={tab === "adminPanel"} onClick={() => selectTab("adminPanel")}>
                {t.tabs.adminPanel}
              </TabButton>
            )}
          </nav>
        )}
      </header>

      <main className="min-h-0 flex-1">
        {tab === "home" && (
          <div className="h-full overflow-y-auto">
            <LandingPage
              onNavigate={selectTab}
              isLoggedIn={!!user}
              onRequestLogin={requestLogin}
            />
          </div>
        )}
        {tab === "map" && <CoverageMap mode="points" onRequestLogin={requestLogin} authBootstrapped={bootstrapped} />}
        {tab === "heatmap" && <CoverageMap mode="heatmap" onRequestLogin={requestLogin} authBootstrapped={bootstrapped} />}
        {tab === "predict" && <CoverageMap mode="predict" onRequestLogin={requestLogin} authBootstrapped={bootstrapped} />}
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
            <AdminPage
              currentUserId={user.id}
              currentUserIsSuperAdmin={user.is_super_admin ?? false}
            />
          </div>
        )}
      </main>

      <AuthModal isOpen={authOpen} onClose={closeAuthModal} />
      {user && (
        <EmailVerifyModal
          isOpen={verifyOpen}
          email={user.email}
          onClose={() => setVerifyOpen(false)}
        />
      )}
    </div>
  );
}

/**
 * @param {{
 *   active: boolean,
 *   onClick: () => void,
 *   children: import("react").ReactNode,
 *   fullWidth?: boolean,
 * }} props
 */
function TabButton({ active, onClick, children, fullWidth = false }) {
  return (
    <button
      onClick={onClick}
      className={
        "rounded-md px-3 py-1.5 text-sm font-medium transition " +
        (fullWidth ? "w-full text-left " : "") +
        (active
          ? "bg-slate-900 text-white"
          : "border border-slate-300 text-slate-700 hover:bg-slate-100")
      }
    >
      {children}
    </button>
  );
}

function HamburgerIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
      aria-hidden="true"
    >
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
      aria-hidden="true"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

function NotFoundPage() {
  const t = strings.app.notFound;
  return (
    <div className="flex h-dvh flex-col items-center justify-center bg-slate-50 px-6">
      <div className="max-w-md text-center">
        <h1 className="text-3xl font-bold text-slate-900">404</h1>
        <h2 className="mt-1 text-lg font-semibold text-slate-800">{t.title}</h2>
        <p className="mt-2 text-sm text-slate-600">{t.hint}</p>
        <a
          href="/"
          className="mt-4 inline-block rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          {t.backHome}
        </a>
      </div>
    </div>
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
