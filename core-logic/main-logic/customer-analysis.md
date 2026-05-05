# Customer Needs Analysis

## LoRa Network Coverage Mapping Platform with ML-Based Coverage Analysis

---

**Document purpose:** This document analyzes the specific needs of each customer persona for a LoRa network mapping software product (web and mobile) that incorporates machine-learning-based coverage analysis. The goal is not to enumerate generic features, but to identify what each persona actually needs in order to make decisions or complete their work.

---

## 1. Persona 1 — IoT Solution Companies (B2B SMEs)

**Priority: High**

This segment is likely to convert earliest because they are actively facing the strategic question: *"Should we use a public LoRa network, or build our own private network?"* Their needs are decision-driven and ROI-focused.

### Key Requirements

- **Bulk coverage check by location list.** Upload a set of coordinates (agricultural sensors, vehicle tracker installation points) and receive predicted coverage probability, RSSI, and SNR values from the ML model.
- **Gateway placement optimizer.** For a given project area (e.g., a 50-hectare farm or a transport corridor), the system should recommend the number of gateways, their optimal placement, and the associated cost. This is the highest-value feature ML can deliver for this segment.
- **Cost comparison module.** Renting public network capacity (Viettel, VNPT) versus building a private network — a financial model tied directly to coverage data.
- **API and SDK access** to embed the coverage layer into their own dashboards.
- **Professional PDF reports** suitable for presenting to investors or end clients.

---

## 2. Persona 2 — Telecom Operators / Network Operators

**Priority: High**

This segment has substantial budget but stringent technical requirements. What they truly want is not "a beautiful map," but rather **reduced drive-test costs** and **optimized CapEx for network expansion**.

### Key Requirements

- **ML-based predictive coverage** using DEM (terrain), OpenStreetMap (building density), and rainfall frequency, enabling coverage forecasts without exhaustive field measurement.
- **"Next-best-gateway" recommender.** An algorithm that suggests the next gateway location to maximize incremental coverage area per unit of cost.
- **Crowdsourced and drive-test data ingestion.** Accept logs from real devices to continuously refine the model.
- **Network health dashboard.** Gateway uptime, packet loss, and capacity utilization metrics.
- **Multi-tenant and SLA reporting** for the operator's enterprise clients.
- **Multi-operator coverage comparison heatmap.** Highly valuable intelligence for the commercial team.

---

## 3. Persona 3 — Smart City Authorities / Government (B2G)

**Priority: Low**

This segment does not "purchase" in the conventional sense; they need deliverables that satisfy reporting obligations to leadership.

### Key Requirements

- **Provincial and city-level overview maps**, vendor-neutral.
- **Reports formatted for administrative use** (PDF with clear charts and structured layout).
- **Integration with existing GIS systems** (ArcGIS, QGIS).
- **Public-facing dashboards** for transparency on coverage availability for citizens.

This persona is less interested in technical detail. Sales typically go through public tendering, resulting in long cycles — assigning a low priority is appropriate.

---

## 4. Persona 4 — Researchers and Engineering Students (Academic)

**Priority: Medium**

This segment will not generate significant direct revenue, but represents a powerful marketing channel and a strong data flywheel.

### Key Requirements

- **Free access (with academic verification).**
- **Raw data export** in standard formats (CSV, JSON, GeoTIFF).
- **Unlimited API access for academic use.**
- **Comparison across propagation models** — Okumura-Hata, COST-231, log-distance — alongside the platform's ML model, for benchmarking purposes.
- **Sandbox environment** allowing users to upload and test their own models.
- **Documentation, tutorials, and sample datasets** suitable for thesis and capstone work.

The investment in this segment is strategic: today's students become tomorrow's engineers at Persona 1 and Persona 2 organizations.

---

## 5. Persona 5 — End Users (Farmers, Small Fleet Operators)

**Priority: High**

This persona requires a fundamentally different UX philosophy. **They do not need to know what RSSI means.** The product for them must:

### Key Requirements

- **Simple Vietnamese-language mobile app.** No "dBm" jargon — only "Good / Weak / No Coverage" indicators.
- **Lookup by address or map tap.** *"Will my coffee farm at this location work?"*
- **Real-time device status.** Is the tracker online? When did it last report?
- **Push notifications** when signal is lost.
- **Completely free.** This segment is highly price-sensitive.

**Note:** Selling directly to this persona is challenging because the customer base is fragmented. Distribution typically goes through Persona 1 or Persona 7, who specify the product on behalf of end users.

---

## 6. Persona 6 — Hardware Vendors

**Priority: Medium**

This persona wants to use the coverage map as a **sales enablement tool.**

### Key Requirements

- **Embeddable widget / iframe** for their e-commerce site (*"check coverage at your address"*).
- **White-label option** with their own branding.
- **Device-network compatibility matrix.** Does device X work with network Y?
- **Co-marketing visibility.** Listing in the platform's "compatible devices" registry.

---

## 7. Persona 7 — System Integrators (SIs)

**Priority: Medium**

System integrators deliver turnkey projects and need tools that shorten pre-sales cycles and accelerate deployment.

### Key Requirements

- **Site survey mode** in the mobile app — log RSSI readings during physical site walks.
- **Automatic Bill of Materials generation** (gateway count, sensors, cabling, antennas) derived from coverage analysis.
- **Project workspace.** Manage multiple parallel projects and invite clients to view results.
- **White-label report templates** for delivery to end customers.

---