// Khoảng cách Haversine (km)
export function haversineDistance(lat1, lng1, lat2, lng2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a =
      Math.sin(dLat / 2) ** 2 +
      Math.cos(lat1 * Math.PI / 180) *
      Math.cos(lat2 * Math.PI / 180) *
      Math.sin(dLng / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  }
  
  // Tìm gateway gần nhất
  export function findNearestGateway(lat, lng, gateways = []) {
    if (!gateways.length) return null;
    let nearest = null, minDist = Infinity;
    for (const gw of gateways) {
      if (!gw.latitude || !gw.longitude) continue;
      const d = haversineDistance(lat, lng, gw.latitude, gw.longitude);
      if (d < minDist) { minDist = d; nearest = gw; }
    }
    return nearest ? { gateway: nearest, distanceKm: minDist } : null;
  }
  
  // Tạo GeoJSON polygon hình tròn
  export function createCirclePolygon(center, radiusKm, steps = 64) {
    const [lng, lat] = center;
    const coords = [];
    for (let i = 0; i <= steps; i++) {
      const angle = (i / steps) * 2 * Math.PI;
      const dLat = (radiusKm / 110.574) * Math.sin(angle);
      const dLng = (radiusKm / (111.32 * Math.cos(lat * Math.PI / 180))) * Math.cos(angle);
      coords.push([lng + dLng, lat + dLat]);
    }
    return { type: "Feature", geometry: { type: "Polygon", coordinates: [coords] } };
  }