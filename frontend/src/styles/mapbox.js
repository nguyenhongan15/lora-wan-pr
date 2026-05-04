// frontend/src/layers/mapbox.js
// File cấu hình tập trung cho Mapbox — chỉnh sửa style tại đây

export const MAP_STYLES = [
    { key: "mapbox://styles/mapbox/standard",              label: "🏙️ Standard 3D" },
    { key: "mapbox://styles/mapbox/dark-v11",              label: "🌑 Tối" },
    { key: "mapbox://styles/mapbox/light-v11",             label: "☀️ Sáng" },
    { key: "mapbox://styles/mapbox/streets-v12",           label: "🗺️ Đường phố" },
    { key: "mapbox://styles/mapbox/outdoors-v12",          label: "🏔️ Địa hình" },
    { key: "mapbox://styles/mapbox/satellite-v9",          label: "🛰️ Vệ tinh" },
  ];
  
  export const LIGHT_PRESETS = [
    { key: "dawn",  label: "🌅 Bình minh" },
    { key: "day",   label: "☀️ Ban ngày" },
    { key: "dusk",  label: "🌆 Hoàng hôn" },
    { key: "night", label: "🌃 Ban đêm" },
  ];
  
  // Standard style có nhà 3D + terrain sẵn, không cần DEM source riêng
  export const isStandard = (style) => !!style?.includes("standard");
  
  // Config object truyền vào prop `config` của <Map>
  export const getConfig = (lightPreset) => ({ basemap: { lightPreset } });