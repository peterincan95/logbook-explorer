// Map settings.
export const mapConfig = {
  // Esri "Modern Antique" basemap (web map item on ArcGIS Online, public).
  basemapItemId: "f35ef07c9ed24020aadd65c8a65d3754",
  center: [20, 15],
  zoom: 2,
  pointSize: 3,          // px
  pointOpacity: 0.7,
  otherPointColor: "#6b6b6b",   // nationalities not listed in nationalities.js
  locationMarkerColor: "#5e1a24",
};

// Data files built by scripts/build_web_data.py, relative to the site root.
export const dataFiles = {
  points: "data/points.csv",
  search: "data/search.tsv",
  locations: "data/locations.json",
};
