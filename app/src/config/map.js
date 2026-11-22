// Map settings. Zoom levels are the standard ArcGIS / Web Mercator levels (2 is
// the whole world, each level up doubles the scale), whatever the basemap uses.
export const mapConfig = {
  // Web map on ArcGIS Online used under the logbook data: its basemap and its
  // layers (place names, coastal hatching). Must be shared publicly, with its layers.
  webMapItemId: "e29833df04384db284b347c57e14e28e",
  // Full logbook records for the popup: public hosted feature layer whose
  // OBJECTID is the point_id in points.csv (published from logbook_points in
  // gis/cliwoc_explorer.gdb).
  logbookItemId: "85cf6855b44e4a49bb1e20fe83953315",
  center: [20, 15],
  zoom: 3,               // starting zoom level

  // Points are drawn from this zoom level in, on top of the voyage lines.
  // When a keyword or search filter is on, points show at every zoom level.
  pointsMinZoom: 7,
  pointSize: 2.1,        // px; grows with zoom per pointSizeByZoom
  // [zoom level, point size in px]: sizes in between are interpolated, and
  // beyond the last stop the size stays the same.
  pointSizeByZoom: [[2, 2.1], [5, 3], [8, 5], [11, 8]],
  pointOpacity: 0.7,     // opacity of each point (0-1); overlapping points add up
  tooltipMinZoom: 7,     // hover tooltips on points start at this zoom level

  // Voyage lines join each ship's points (coloured by nationality, under the
  // points) and show at every zoom level. Only voyages with at least one point
  // matching the filters are drawn.
  showLines: true,
  lineWidth: 0.6,        // px
  lineOpacity: 0.2,      // opacity of each line (0-1); overlapping lines add up
  // The voyage line while one voyage is shown (popup's Show Voyage button)
  voyageLineWidth: 2,
  voyageLineOpacity: 0.9,

  otherPointColor: "#6b6b6b",   // nationalities not listed in nationalities.js
  locationMarkerColor: "#5e1a24",
};

// Data files built by scripts/build_web_data.py, relative to the site root.
export const dataFiles = {
  points: "data/points.csv",
  lines: "data/lines.geojson",
  search: "data/search.tsv",
  locations: "data/locations.json",
};
