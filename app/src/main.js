import "@fontsource/playfair-display/600.css";
import "@fontsource/playfair-display/700.css";
import "@fontsource/alegreya-sans/400.css";
import "@fontsource/alegreya-sans/500.css";
import "@fontsource/alegreya-sans/700.css";
import "@arcgis/core/assets/esri/themes/light/main.css";
import "./style.css";

import "@esri/calcite-components/components/calcite-block";
import "@esri/calcite-components/components/calcite-combobox";
import "@esri/calcite-components/components/calcite-combobox-item";
import "@esri/calcite-components/components/calcite-icon";
import "@esri/calcite-components/components/calcite-input";
import "@esri/calcite-components/components/calcite-popover";
import "@esri/calcite-components/components/calcite-slider";
import "@esri/calcite-components/components/calcite-tooltip";
import "@arcgis/map-components/components/arcgis-map";
import "@arcgis/map-components/components/arcgis-zoom";
import "@arcgis/map-components/components/arcgis-home";

import Viewpoint from "@arcgis/core/Viewpoint.js";
import CSVLayer from "@arcgis/core/layers/CSVLayer.js";
import GeoJSONLayer from "@arcgis/core/layers/GeoJSONLayer.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import Graphic from "@arcgis/core/Graphic.js";
import Color from "@arcgis/core/Color.js";
import FeatureFilter from "@arcgis/core/layers/support/FeatureFilter.js";
import * as reactiveUtils from "@arcgis/core/core/reactiveUtils.js";

import { strings } from "./config/strings.js";
import { mapConfig, dataFiles } from "./config/map.js";
import { nationalities } from "./config/nationalities.js";
import keywordsCsv from "./config/keywords.csv?raw";
import { createState, buildWhere, keywordActive } from "./filters.js";
import { loadSearchIndex, compileWords, compileQuery, matchIds } from "./search.js";
import { buildPanel } from "./panel.js";
import { createPopup } from "./popup.js";

const dataUrl = (path) => `${import.meta.env.BASE_URL}${path}`;
// Map scale at a standard ArcGIS / Web Mercator zoom level. All zoom levels in
// config/map.js use these, whatever tiling the basemap uses (a basemap with
// 512 px tiles numbers its levels one lower, so view.zoom isn't used).
const scaleAtZoom = (zoom) => 591657527.591555 / 2 ** zoom;
// True when the view is at or closer than a zoom level (small margin for rounding)
const zoomedTo = (view, zoom) => view.scale <= scaleAtZoom(zoom) * 1.001;
// A colour (hex or name) with the given opacity (0-1)
const withAlpha = (color, opacity) => {
  const c = new Color(color);
  c.a = opacity;
  return c;
};

function parseKeywords(csv) {
  return csv
    .split(/\r?\n/)
    .slice(1)
    .map((line) => {
      const comma = line.indexOf(",");
      return comma > 0 ? { label: line.slice(0, comma).trim(), words: line.slice(comma + 1).trim() } : null;
    })
    .filter((k) => k && k.label && k.words);
}

function pointsLayer() {
  // Opacity is set on each point's colour, not the layer, so overlapping
  // points build up and look more solid.
  const marker = (color) => ({
    type: "simple-marker", size: mapConfig.pointSize, color: withAlpha(color, mapConfig.pointOpacity), outline: null,
  });
  return new CSVLayer({
    url: dataUrl(dataFiles.points),
    title: strings.pageTitle,
    latitudeField: "lat",
    longitudeField: "lon",
    outFields: ["point_id", "nat", "company", "origin", "dest", "year", "ship", "date", "track"],
    popupEnabled: false,
    renderer: {
      type: "unique-value",
      field: "nat",
      defaultSymbol: marker(mapConfig.otherPointColor),
      uniqueValueInfos: nationalities.map((n) => ({ value: n.value, label: n.label, symbol: marker(n.color) })),
      // Points grow as you zoom in: size by view scale (Web Mercator scale at zoom z)
      visualVariables: [{
        type: "size",
        valueExpression: "$view.scale",
        stops: mapConfig.pointSizeByZoom
          .map(([zoom, size]) => ({ value: scaleAtZoom(zoom), size }))
          .sort((a, b) => a.value - b.value),
      }],
    },
  });
}

// Voyage lines (lines.geojson): feature n is track n, and points carry the
// track number, so the lines to show are the tracks of the points showing.
function lineRenderer(width, opacity) {
  const line = (color) => ({ type: "simple-line", width, color: withAlpha(color, opacity) });
  return {
    type: "unique-value",
    field: "nat",
    defaultSymbol: line(mapConfig.otherPointColor),
    uniqueValueInfos: nationalities.map((n) => ({ value: n.value, label: n.label, symbol: line(n.color) })),
  };
}

function linesLayer() {
  return new GeoJSONLayer({
    url: dataUrl(dataFiles.lines),
    title: "voyages",
    outFields: ["nat"],
    popupEnabled: false,
    renderer: lineRenderer(mapConfig.lineWidth, mapConfig.lineOpacity),
  });
}

// Track numbers of the points matching the filter
async function visibleTracks(layer, where, objectIds) {
  const { features } = await layer.queryFeatures({
    where: `(${where}) AND track IS NOT NULL`,
    objectIds,
    groupByFieldsForStatistics: ["track"],
    outStatistics: [{ statisticType: "count", onStatisticField: "track", outStatisticFieldName: "n" }],
  });
  return features.map((f) => Number(f.attributes.track));
}

async function yearHistogram(layer) {
  const { features } = await layer.queryFeatures({
    where: "year IS NOT NULL",
    groupByFieldsForStatistics: ["year"],
    outStatistics: [{ statisticType: "count", onStatisticField: "year", outStatisticFieldName: "n" }],
  });
  const rows = features.map((f) => [Number(f.attributes.year), Number(f.attributes.n)]).sort((a, b) => a[0] - b[0]);
  return { min: rows[0][0], max: rows.at(-1)[0], histogram: rows };
}

// Hover tooltip: ship name over the date. A calcite-tooltip is anchored to an
// invisible element moved to the cursor; each pointer move hit-tests the
// points layer, and results from older moves are ignored. Only active from
// mapConfig.tooltipMinZoom in, or at any zoom while anyZoom() is true (a
// keyword filter or a single voyage is shown), and not for touch (no hover).
// Point size (px) at a view scale, following mapConfig.pointSizeByZoom
function pointSizeAt(scale) {
  const zoom = Math.log2(scaleAtZoom(0) / scale);
  const stops = mapConfig.pointSizeByZoom;
  if (zoom <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [z0, s0] = stops[i - 1], [z1, s1] = stops[i];
    if (zoom <= z1) return s0 + ((zoom - z0) / (z1 - z0)) * (s1 - s0);
  }
  return stops[stops.length - 1][1];
}

// A light ring around the log entry or location under the cursor (and the
// pointer cursor), for anything that can be clicked. layers(): the layers to
// test right now; sizeOf(hit): the hovered symbol's size in px.
function setUpHoverRing(view, ringLayer, layers, sizeOf) {
  let latestMove = 0;
  let current = null;
  const clear = () => {
    current = null;
    ringLayer.removeAll();
    view.container.style.cursor = "";
  };
  view.on("pointer-move", async (event) => {
    const move = ++latestMove;
    const include = layers();
    if (!include.length || event.pointerType === "touch") return clear();
    const { results } = await view.hitTest(event, { include });
    if (move !== latestMove) return;
    const hit = results.find((r) => r.type === "graphic");
    if (!hit) return clear();
    const key = `${hit.layer.uid}:${hit.graphic.getObjectId?.() ?? hit.graphic.uid}`;
    view.container.style.cursor = "pointer";
    if (key === current) return;
    current = key;
    const size = sizeOf(hit) + mapConfig.hoverRingGap * 2;
    ringLayer.removeAll();
    ringLayer.addMany([
      // thin dark edge so the light ring shows on the pale basemap
      new Graphic({ geometry: hit.graphic.geometry, symbol: {
        type: "simple-marker", style: "circle", size: size + mapConfig.hoverRingWidth,
        color: [0, 0, 0, 0], outline: { color: [0, 0, 0, 0.45], width: mapConfig.hoverRingWidth + 1.5 },
      } }),
      new Graphic({ geometry: hit.graphic.geometry, symbol: {
        type: "simple-marker", style: "circle", size: size + mapConfig.hoverRingWidth,
        color: [0, 0, 0, 0], outline: { color: mapConfig.hoverRingColor, width: mapConfig.hoverRingWidth },
      } }),
    ]);
  });
  view.on("pointer-leave", () => { latestMove++; clear(); });
  reactiveUtils.watch(() => view.scale, clear);
}

function setUpTooltip(view, layer, anyZoom = () => false) {
  const active = () => anyZoom() || zoomedTo(view, mapConfig.tooltipMinZoom);
  const anchor = document.getElementById("tooltip-anchor");
  const tooltip = document.getElementById("point-tooltip");
  const shipEl = document.getElementById("tooltip-ship");
  const dateEl = document.getElementById("tooltip-date");
  tooltip.label = strings.tooltipLabel;
  const dateFormat = new Intl.DateTimeFormat(strings.dateLocale, { ...strings.dateFormat, timeZone: "UTC" });
  // CSVLayer reads the date column as a date field (epoch milliseconds, UTC)
  const formatDate = (date, year) => {
    if (date == null || date === "") return String(year ?? "");
    const d = typeof date === "number" ? new Date(date) : new Date(`${date}T00:00:00Z`);
    return Number.isNaN(d.getTime()) ? String(year ?? "") : dateFormat.format(d);
  };

  let latestMove = 0;
  const hide = () => { tooltip.open = false; };
  view.on("pointer-move", async (event) => {
    const move = ++latestMove;
    if (!active() || event.pointerType === "touch") return hide();
    const { results } = await view.hitTest(event, { include: [layer] });
    if (move !== latestMove) return;
    const hit = results.find((r) => r.type === "graphic");
    if (!hit) return hide();
    const { ship, date, year } = hit.graphic.attributes;
    shipEl.textContent = ship || "";
    dateEl.textContent = formatDate(date, year);
    const rect = view.container.getBoundingClientRect();
    anchor.style.left = `${rect.left + event.x}px`;
    anchor.style.top = `${rect.top + event.y}px`;
    tooltip.open = true;
    tooltip.reposition();
  });
  view.on("pointer-leave", () => {
    latestMove++;
    hide();
  });
  reactiveUtils.watch(() => view.scale, () => { if (!active()) hide(); });
}

async function main() {
  document.title = strings.pageTitle;
  document.getElementById("app-title").textContent = strings.appTitle;
  document.getElementById("app-subtitle").textContent = strings.appSubtitle;
  const mapEl = document.querySelector("arcgis-map");
  // The whole web map (basemap plus its own layers, e.g. place names and
  // coastal hatching); the logbook layers are added on top of it. Its saved
  // view is replaced by the start view in map.js, which Home also returns to.
  mapEl.itemId = mapConfig.webMapItemId;
  await mapEl.viewOnReady();
  mapEl.view.popupEnabled = false;          // the app's own popup handles clicks
  const start = new Viewpoint({
    targetGeometry: { type: "point", longitude: mapConfig.center[0], latitude: mapConfig.center[1] },
    scale: scaleAtZoom(mapConfig.zoom),
  });
  await mapEl.view.goTo(start, { animate: false });
  document.querySelector("arcgis-home").viewpoint = start;

  const layer = pointsLayer();
  const lines = mapConfig.showLines ? linesLayer() : null;
  const markers = new GraphicsLayer({ title: "locations" });
  mapEl.map.addMany([lines, layer, markers].filter(Boolean));
  // The web map's location layers go above the logbook data so labels stay
  // readable; clicking a location opens its popup (Show Voyages)
  const placeLayers = mapEl.map.layers.filter((l) => /^locations \(/i.test(l.title)).toArray();
  for (const l of placeLayers) {
    mapEl.map.reorder(l, mapEl.map.layers.length - 1);
    l.outFields = ["location_id", "common_name", "modern_name"];
  }
  // Lines load on their own so the points aren't held up
  const lineViewReady = lines ? mapEl.whenLayerView(lines).catch((err) => console.error(err)) : null;

  const [layerView, locations, years] = await Promise.all([
    mapEl.whenLayerView(layer),
    fetch(dataUrl(dataFiles.locations)).then((r) => r.json()),
    layer.load().then(() => yearHistogram(layer)),
  ]);
  const total = await layer.queryFeatureCount();

  // Points show from mapConfig.pointsMinZoom in, or at any zoom while a
  // keyword/search filter is on (minScale 0 = no limit). The small margin keeps
  // them on at exactly that zoom level.
  const showPoints = (always) => {
    layer.minScale = always ? 0 : scaleAtZoom(mapConfig.pointsMinZoom) * 1.001;
  };
  showPoints(false);
  const byId = new Map(locations.map((l) => [l.id, l]));
  const keywords = parseKeywords(keywordsCsv);
  const keywordPatterns = new Map(keywords.map((k) => [k.label, compileWords(k.words)]));

  const state = createState();
  let run = 0;
  // Overlays on top of the panel filters (which stay set and come back with the
  // panel's back button): one voyage (popup "Show Voyage"), or every voyage
  // from or to one location (location popup "Show Voyages").
  let voyage = null;   // track number while "Show Voyage" is on, else null
  let place = null;    // location_id while "Show Voyages" is on, else null

  async function keywordIds() {
    const patterns = [...state.keywords].map((k) => keywordPatterns.get(k));
    const q = compileQuery(state.text);
    if (q) patterns.push(q);
    panel.setSearching(true);
    try {
      const index = await loadSearchIndex(dataUrl(dataFiles.search));
      return matchIds(index, patterns.filter(Boolean));
    } finally {
      panel.setSearching(false);
    }
  }

  function showLocations() {
    markers.removeAll();
    for (const [id, kind] of [[state.origin, "origin"], [state.destination, "destination"]]) {
      const loc = byId.get(id);
      if (!loc || loc.lat == null) continue;
      markers.add(new Graphic({
        geometry: { type: "point", longitude: loc.lon, latitude: loc.lat },
        symbol: {
          type: "simple-marker", style: kind === "origin" ? "circle" : "diamond", size: 14,
          color: [255, 255, 255, 0.85], outline: { color: mapConfig.locationMarkerColor, width: 2.5 },
        },
      }));
    }
  }

  // One voyage on its own (from the popup's Show Voyage button). The panel
  // filters stay set and come back with the panel's back button.
  // Line style: stronger while one voyage is shown on its own
  const lineStyles = {
    all: lineRenderer(mapConfig.lineWidth, mapConfig.lineOpacity),
    voyage: lineRenderer(mapConfig.voyageLineWidth, mapConfig.voyageLineOpacity),
  };
  let lineStyle = "all";
  const setLineStyle = (style) => {
    if (lines && style !== lineStyle) lines.renderer = lineStyles[style];
    lineStyle = style;
  };

  async function applyVoyage(mine) {
    const where = `track = ${voyage}`;
    setLineStyle("voyage");
    showPoints(true);
    layerView.filter = new FeatureFilter({ where });
    markers.removeAll();
    const shown = await layer.queryFeatureCount({ where });
    if (mine !== run) return;
    panel.setCount(shown, 1);
    if (lines) filterLines(mine, [voyage]);
  }

  async function applyPlace(mine) {
    const where = `origin = ${place} OR dest = ${place}`;
    setLineStyle("all");
    showPoints(false);
    layerView.filter = new FeatureFilter({ where });
    markers.removeAll();
    const loc = byId.get(place);
    if (loc?.lat != null) {
      markers.add(new Graphic({
        geometry: { type: "point", longitude: loc.lon, latitude: loc.lat },
        symbol: {
          type: "simple-marker", style: "circle", size: 14,
          color: [255, 255, 255, 0.85], outline: { color: mapConfig.locationMarkerColor, width: 2.5 },
        },
      }));
    }
    const [shown, tracks] = await Promise.all([layer.queryFeatureCount({ where }), visibleTracks(layer, where, null)]);
    if (mine !== run) return;
    panel.setCount(shown, tracks.length);
    if (lines) filterLines(mine, tracks);
  }

  function showPlaceVoyages(locationId) {
    voyage = null;
    place = locationId;
    panel.setVoyageMode(true);
    popup.close();
    applyPlace(++run);
  }

  async function showVoyage(track) {
    place = null;
    voyage = track;
    panel.setVoyageMode(true);
    popup.close();
    const mine = ++run;
    const [extent] = await Promise.all([layer.queryExtent({ where: `track = ${track}` }), applyVoyage(mine)]);
    if (mine === run && extent.extent) {
      const ext = extent.extent;
      await mapEl.view.goTo(ext.width || ext.height ? ext.expand(1.3) : { target: ext.center, zoom: 8 })
        .catch(() => {});
    }
  }

  function leaveVoyage() {
    if (voyage == null && place == null) return false;
    voyage = place = null;
    panel.setVoyageMode(false);
    return true;
  }

  async function apply() {
    const mine = ++run;
    if (voyage != null) return applyVoyage(mine);
    if (place != null) return applyPlace(mine);
    setLineStyle("all");
    const where = buildWhere(state);
    showPoints(keywordActive(state));
    let objectIds = null;
    if (keywordActive(state)) {
      objectIds = await keywordIds();
      if (mine !== run) return;               // a newer change superseded this one
    }
    // An empty objectIds list would show everything, so no matches -> 1=0.
    const filter = objectIds && objectIds.length === 0
      ? new FeatureFilter({ where: "1=0" })
      : new FeatureFilter({ where, objectIds });
    layerView.filter = filter;
    showLocations();
    const none = objectIds?.length === 0;
    const [shown, tracks] = none ? [0, []] : await Promise.all([
      layer.queryFeatureCount({ where, objectIds }),
      visibleTracks(layer, where, objectIds),
    ]);
    if (mine !== run) return;
    panel.setCount(shown, tracks.length);
    if (lines) filterLines(mine, where === "1=1" && !objectIds ? null : tracks);
  }

  // tracks: voyage numbers to draw (= line object IDs), or null for all
  async function filterLines(mine, tracks) {
    const lineView = await lineViewReady;
    if (!lineView || mine !== run) return;
    lineView.filter = !tracks ? null
      : tracks.length ? new FeatureFilter({ objectIds: tracks }) : new FeatureFilter({ where: "1=0" });
  }

  const panel = buildPanel(document.querySelector("#panel"), {
    state, locations, keywords, years,
    onChange: () => { leaveVoyage(); apply(); },      // changing a filter ends the single-voyage view
    onVoyageBack: () => { leaveVoyage(); apply(); },
    onKeywordOpen: () => loadSearchIndex(dataUrl(dataFiles.search)).catch(() => {}),
  });

  // Click a point (where points are showing) for its popup
  const popup = createPopup(mapEl.view, {
    itemId: mapConfig.logbookItemId, locations: byId, onShowVoyage: showVoyage, onShowPlaceVoyages: showPlaceVoyages,
    // Keyword chips and search text that are on: highlighted in the popup
    getHighlights: () => [...[...state.keywords].map((k) => keywordPatterns.get(k)), compileQuery(state.text)]
      .filter(Boolean),
  });
  // Click a location (drawn above the points, so it wins) or a point
  mapEl.view.on("click", async (event) => {
    const include = [...placeLayers, ...(layerView.suspended ? [] : [layer])];
    const { results } = await mapEl.view.hitTest(event, { include });
    const hit = results.find((r) => r.type === "graphic");
    if (!hit) return popup.close();
    const a = hit.graphic.attributes;
    if (hit.layer === layer) popup.open(hit.graphic.geometry, a.point_id, a.track, a);
    else popup.openLocation(hit.graphic.geometry, a);
  });
  panel.setCount(total, (await visibleTracks(layer, "1=1", null)).length);
  setUpTooltip(mapEl.view, layer, () => voyage != null || keywordActive(state));
  // Ring on hover: locations always, log entries wherever they're showing
  const ring = new GraphicsLayer({ title: "hover", listMode: "hide" });
  mapEl.map.add(ring);
  setUpHoverRing(mapEl.view, ring,
    () => [...placeLayers, ...(layerView.suspended ? [] : [layer])],
    (hit) => (hit.layer === layer ? pointSizeAt(mapEl.view.scale) : mapConfig.locationSymbolSize));
  document.body.classList.remove("loading");
}

main().catch((err) => {
  console.error(err);
  document.body.classList.remove("loading");
});
