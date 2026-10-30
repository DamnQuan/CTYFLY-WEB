/**
 * Great-circle distance utilities WGS84 spherical approximation
 * All distances in Nautical Miles NM
 */

const EARTH_RADIUS_NM = 3440.065; // mean radius in NM

/**
 * Convert degrees to radians
 */
function toRad(deg) {
  return deg * Math.PI / 180;
}

/**
 * Haversine great-circle distance between two lat/lon points in NM
 * @param {number} lat1
 * @param {number} lon1
 * @param {number} lat2
 * @param {number} lon2
 * @returns {number} distance in NM
 */
function distanceNM(lat1, lon1, lat2, lon2) {
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return EARTH_RADIUS_NM * c;
}

/**
 * Calculate distance between two waypoint objects {Latitude, Longtitude}
 */
function distanceBetween(wp1, wp2) {
  return distanceNM(wp1.Latitude, wp1.Longtitude, wp2.Latitude, wp2.Longtitude);
}

module.exports = {
  distanceNM,
  distanceBetween,
  EARTH_RADIUS_NM
};
