/**
 * NavBar.jsx — Floating horizontal navigation, always visible.
 *
 * Layout: [☰ 📡 LoRa] [link1] [link2] ... — cùng 1 hàng, không trượt/ẩn.
 *
 * Tuân thủ:
 *   - WCAG: <nav> semantic, aria-current cho link đang active
 *   - Component-driven, i18n qua strings.js
 */

import S from "../strings";

const LINKS = [
  { href: "/",            label: S.nav.map },
  { href: "/simulator",   label: S.nav.simulator },
  { href: "/health",      label: S.nav.health },
  { href: "/calibration", label: S.nav.calibration },
  { href: "/compare",     label: S.nav.compare },
  { href: "/sandbox",     label: S.nav.sandbox },
  { href: "/snapshots",   label: S.nav.snapshots },
  { href: "/webhooks",    label: S.nav.webhooks },
];

function isActive(href, pathname) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}


export default function NavBar() {
  const pathname = window.location.pathname;

  return (
    <div style={wrapStyle}>
      
      <nav aria-label="Main navigation" style={navStyle}>
        {LINKS.map(link => {
          const active = isActive(link.href, pathname);
          return (
            <a
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              style={linkStyle(active)}
            >
              {link.label}
            </a>
          );
        })}
      </nav>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────

const wrapStyle = {
  position: "fixed", top: 12, left: "50%",
  transform: "translateX(-50%)", zIndex: 1500,
  display: "flex", alignItems: "center", gap: 8,
};

const navStyle = {
  display: "flex", alignItems: "center", gap: 4,
  padding: "6px 10px",
  background: "rgba(15,23,42,0.97)",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 8,
  backdropFilter: "blur(8px)",
  boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
};

const linkStyle = (active) => ({
  display: "block",
  padding: "6px 12px",
  fontSize: 13, fontWeight: 500,
  color: active ? "#fff" : "#cbd5e1",
  background: active ? "rgba(124,58,237,0.4)" : "transparent",
  borderRadius: 6,
  textDecoration: "none",
  whiteSpace: "nowrap",
});