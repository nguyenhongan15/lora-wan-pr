# LoRa Coverage Map — Frontend

A React-based interactive map application for visualizing LoRa signal coverage in Da Nang city. It displays drive-test measurements, gateway locations, heatmaps, and IDW-interpolated signal grids on a Mapbox GL map.

## Features

- **Scatter view** — plot raw RSSI measurement points with popup details
- **Heatmap view** — render signal intensity as a continuous heatmap
- **ML/IDW grid view** — display IDW-interpolated coverage predictions
- **Uncertainty layer** — visualize prediction uncertainty across the grid
- **Gateway markers** — show LoRa gateway positions with configurable range circles
- **Filtering** — filter measurements by minimum RSSI and Spreading Factor (SF7–SF12)
- **Map styles** — switch between Mapbox Standard, Satellite, and Streets styles with light preset control

## Tech Stack

- [React 19](https://react.dev/)
- [Vite](https://vitejs.dev/)
- [react-map-gl](https://visgl.github.io/react-map-gl/) + [Mapbox GL JS](https://docs.mapbox.com/mapbox-gl-js/)
- [Axios](https://axios-http.com/)

## Prerequisites

- Node.js >= 18
- A [Mapbox access token](https://account.mapbox.com/)
- The backend API running (see backend README)

## Installation

1. **Clone the repository and navigate to the frontend directory:**

   ```bash
   git clone <repo-url>
   cd lora-coverage/frontend
   ```

2. **Install dependencies:**

   ```bash
   npm install
   ```

3. **Create a `.env` file in the `frontend/` directory:**

   ```env
   VITE_MAPBOX_TOKEN=your_mapbox_access_token_here
   ```

4. **Start the development server:**

   ```bash
   npm run dev
   ```

   The app will be available at `http://localhost:5173`.

## Available Scripts

| Script | Description |
|--------|-------------|
| `npm run dev` | Start the Vite development server with HMR |
| `npm run build` | Build for production (output to `dist/`) |
| `npm run preview` | Preview the production build locally |
| `npm run lint` | Run ESLint |
