// Map settings.
export const mapConfig = {
  // Esri "Modern Antique" basemap (web map item on ArcGIS Online, public).
  basemapItemId: "f35ef07c9ed24020aadd65c8a65d3754",
  center: [20, 15],
  zoom: 2,
  pointSize: 2.1,        // px at the world view; grows with zoom per pointSizeByZoom
  // [zoom level, point size in px]: sizes in between are interpolated, and
  // beyond the last stop the size stays the same. World view is zoom 2.
  pointSizeByZoom: [[2, 2.1], [5, 3], [8, 5], [11, 8]],
  pointOpacity: 0.7,
  tooltipMinZoom: 6,    // hover tooltips on points start at this zoom level (world view is 2)
  otherPointColor: "#6b6b6b",   // nationalities not listed in nationalities.js
  locationMarkerColor: "#5e1a24",
};

// Data files built by scripts/build_web_data.py, relative to the site root.
export const dataFiles = {
  points: "data/points.csv",
  search: "data/search.tsv",
  locations: "data/locations.json",
};
