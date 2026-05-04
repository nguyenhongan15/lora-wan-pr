/**
 * ExportButtons.jsx — link tải GeoJSON / KML / BoQ / PDF.
 */

import { api } from "../api";
import S from "../strings";

const linkStyle = {
  display:    "block",
  padding:    "6px 10px",
  borderRadius: 7,
  background: "rgba(255,255,255,0.07)",
  color:      "#d1d5db",
  fontSize:   12,
  fontWeight: 500,
  textDecoration: "none",
  textAlign:  "left",
  marginTop:  4,
};

export default function ExportButtons({ campaignId }) {
  if (!campaignId) return null;
  return (
    <>
      <a href={api.exportGeoJSONUrl(campaignId)} style={linkStyle} download>
        {S.toolbar.exportGeoJson}
      </a>
      <a href={api.exportKMLUrl(campaignId)} style={linkStyle} download>
        {S.toolbar.exportKml}
      </a>
      <a href={api.exportBoQUrl(campaignId)} style={linkStyle} download>
        {S.toolbar.exportBoq}
      </a>
      <a href={api.reportPdfUrl(campaignId)} style={linkStyle} download>
        {S.toolbar.exportPdf}
      </a>
    </>
  );
}