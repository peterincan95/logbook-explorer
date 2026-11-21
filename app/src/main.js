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
import "@arcgis/map-components/components/arcgis-map";
import "@arcgis/map-components/components/arcgis-zoom";
import "@arcgis/map-components/components/arcgis-home";

import Basemap from "@arcgis/core/Basemap.js";
import CSVLayer from "@arcgis/core/layers/CSVLayer.js";
import GraphicsLayer from "@arcgis/core/layers/GraphicsLayer.js";
import Graphic from "@arcgis/core/Graphic.js";
import FeatureFilter from "@arcgis/core/layers/support/FeatureFilter.js";

import { strings } from "./config/strings.js";
import { mapConfig, dataFiles } from "./config/map.js";
import { nationalities } from "./config/nationalities.js";
import keywordsCsv from "./config/keywords.csv?raw";
import { createState, buildWhere, keywordActive } from "./filters.js";
import { loadSearchIndex, compileWords, compileQuery, matchIds } from "./search.js";
import { buildPanel } from "./panel.js";

const dataUrl = (path) => `${import.meta.env.BASE_URL}${path}`;

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
  const marker = (color) => ({
    type: "simple-marker", size: mapConfig.pointSize, color, outline: null,
  });
  return new CSVLayer({
    url: dataUrl(dataFiles.points),
    title: strings.pageTitle,
    latitudeField: "lat",
    longitudeField: "lon",
    outFields: ["nat", "company", "origin", "dest", "year"],
    opacity: mapConfig.pointOpacity,
    popupEnabled: false,
    renderer: {
      type: "unique-value",
      field: "nat",
      defaultSymbol: marker(mapConfig.otherPointColor),
      uniqueValueInfos: nationalities.map((n) => ({ value: n.value, label: n.label, symbol: marker(n.point) })),
    },
  });
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

async function main() {
  document.title = strings.pageTitle;
  const mapEl = document.querySelector("arcgis-map");
  mapEl.basemap = new Basemap({ portalItem: { id: mapConfig.basemapItemId } });
  mapEl.center = mapConfig.center;
  mapEl.zoom = mapConfig.zoom;
  await mapEl.viewOnReady();

  const layer = pointsLayer();
  const markers = new GraphicsLayer({ title: "locations" });
  mapEl.map.addMany([layer, markers]);

  const [layerView, locations, years] = await Promise.all([
    mapEl.whenLayerView(layer),
    fetch(dataUrl(dataFiles.locations)).then((r) => r.json()),
    layer.load().then(() => yearHistogram(layer)),
  ]);
  const total = await layer.queryFeatureCount();
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
    const shown = objectIds?.length === 0 ? 0 : await layer.queryFeatureCount({ where, objectIds });
    if (mine === run) panel.setCount(shown, total);
  }

  const panel = buildPanel(document.querySelector("#panel"), {
    state, onChange: apply, locations, keywords, years,
    onKeywordOpen: () => loadSearchIndex(dataUrl(dataFiles.search)).catch(() => {}),
  });
  panel.setCount(total, total);
  document.body.classList.remove("loading");
}

main().catch((err) => {
  console.error(err);
  document.body.classList.remove("loading");
});
