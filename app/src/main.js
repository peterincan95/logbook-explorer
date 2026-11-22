import "@fontsource/cinzel/600.css";
import "@fontsource/cinzel/700.css";
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

import Basemap from "@arcgis/core/Basemap.js";
import PortalItem from "@arcgis/core/portal/PortalItem.js";
import VectorTileLayer from "@arcgis/core/layers/VectorTileLayer.js";
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
    outFields: ["nat", "company", "origin", "dest", "year", "ship", "date", "track"],
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
function linesLayer() {
  // Opacity is set on each line's colour, not the layer, so where lines
  // overlap they build up and look more solid.
  const line = (color) => ({ type: "simple-line", width: mapConfig.lineWidth, color: withAlpha(color, mapConfig.lineOpacity) });
  return new GeoJSONLayer({
    url: dataUrl(dataFiles.lines),
    title: "voyages",
    outFields: ["nat"],
    popupEnabled: false,
    renderer: {
      type: "unique-value",
      field: "nat",
      defaultSymbol: line(mapConfig.otherPointColor),
      uniqueValueInfos: nationalities.map((n) => ({ value: n.value, label: n.label, symbol: line(n.color) })),
    },
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

// The basemap item can be a vector tile style (e.g. one made in the Vector
// Tile Style Editor) or a web map used as a basemap.
async function loadBasemap(id) {
  const item = new PortalItem({ id });
  await item.load();
  if (item.type === "Vector Tile Service") {
    return new Basemap({ baseLayers: [new VectorTileLayer({ portalItem: item })], title: item.title });
  }
  return new Basemap({ portalItem: item });
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
// mapConfig.tooltipMinZoom in, and not for touch (no hover).
function setUpTooltip(view, layer) {
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
  const hide = () => {
    tooltip.open = false;
    view.container.style.cursor = "";
  };
  view.on("pointer-move", async (event) => {
    const move = ++latestMove;
    if (!zoomedTo(view, mapConfig.tooltipMinZoom) || event.pointerType === "touch") return hide();
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
    view.container.style.cursor = "pointer";
    tooltip.open = true;
    tooltip.reposition();
  });
  view.on("pointer-leave", () => {
    latestMove++;
    hide();
  });
  reactiveUtils.watch(() => view.scale, () => { if (!zoomedTo(view, mapConfig.tooltipMinZoom)) hide(); });
}

async function main() {
  document.title = strings.pageTitle;
  const mapEl = document.querySelector("arcgis-map");
  mapEl.basemap = await loadBasemap(mapConfig.basemapItemId);
  mapEl.center = mapConfig.center;
  mapEl.scale = scaleAtZoom(mapConfig.zoom);
  await mapEl.viewOnReady();

  const layer = pointsLayer();
  const lines = mapConfig.showLines ? linesLayer() : null;
  const markers = new GraphicsLayer({ title: "locations" });
  mapEl.map.addMany([lines, layer, markers].filter(Boolean));
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

  async function apply() {
    const mine = ++run;
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
    state, onChange: apply, locations, keywords, years,
    onKeywordOpen: () => loadSearchIndex(dataUrl(dataFiles.search)).catch(() => {}),
  });
  panel.setCount(total, (await visibleTracks(layer, "1=1", null)).length);
  setUpTooltip(mapEl.view, layer);
  document.body.classList.remove("loading");
}

main().catch((err) => {
  console.error(err);
  document.body.classList.remove("loading");
});
