import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App              from "./App";
import MobilePage       from "./pages/MobilePage";
import SimulatorPage    from "./pages/SimulatorPage";
import HealthPage       from "./pages/HealthPage";
import CalibrationPage  from "./pages/CalibrationPage";
import ComparePage      from "./pages/ComparePage";
import SandboxPage      from "./pages/SandboxPage";
import SnapshotsPage    from "./pages/SnapshotsPage";
import WebhooksPage     from "./pages/WebhooksPage";

const path = window.location.pathname;

function pick() {
  if (path === "/m" || path.startsWith("/m/") || path.startsWith("/mobile")) return MobilePage;
  if (path.startsWith("/simulator"))   return SimulatorPage;
  if (path.startsWith("/health"))      return HealthPage;
  if (path.startsWith("/calibration")) return CalibrationPage;
  if (path.startsWith("/compare"))     return ComparePage;
  if (path.startsWith("/sandbox"))     return SandboxPage;
  if (path.startsWith("/snapshots"))   return SnapshotsPage;
  if (path.startsWith("/webhooks"))    return WebhooksPage;
  return App;
}

const Page = pick();

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <Page />
  </StrictMode>
);