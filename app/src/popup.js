// Popup for a clicked log entry. The map's points only carry the fields the
// filters need, so the full record is fetched from the hosted logbook layer
// (its OBJECTID is the point_id in points.csv). The card is anchored to the
// clicked point and follows it as the map moves. Sections with no data in the
// entry are left out.
import PortalItem from "@arcgis/core/portal/PortalItem.js";
import * as reactiveUtils from "@arcgis/core/core/reactiveUtils.js";

import { el } from "./dom.js";
import { strings } from "./config/strings.js";
import { nationalities } from "./config/nationalities.js";
import { companies } from "./config/companies.js";
import { flags } from "./config/flags.js";
import shipTypesCsv from "./config/ship_types.csv?raw";
import ranksCsv from "./config/ranks.csv?raw";

const MEMO_FIELDS = ["LifeOnBoard_en", "CargoMemo_en", "EncRem_en", "BiologyMemo_en", "WarsAndFightsMemo_en",
                     "ShipAndRigMemo_en", "OtherShipInformation_en", "OtherRem_en"];
const FIELDS = ["ShipName", "YR", "MO", "DY", "Nationality", "Company", "ShipType",
                "Name1", "Rank1", "Name2", "Rank2", "Name3", "Rank3",
                "origin_location_id", "destination_location_id",
                "Weather_en", "AllWindDirections_en", "AllWindForces_en", "StateSea_en", ...MEMO_FIELDS];

// "as_written,english" CSV -> Map (keys uppercased, spaces collapsed)
const norm = (s) => String(s ?? "").trim().replace(/\s+/g, " ").toUpperCase();
function lookup(csv) {
  const map = new Map();
  for (const line of csv.split(/\r?\n/).slice(1)) {
    const m = line.match(/^("([^"]*)"|[^,]*),("([^"]*)"|.*)$/);
    if (m) map.set(norm(m[2] ?? m[1]), (m[4] ?? m[3]).trim());
  }
  return map;
}
const shipTypes = lookup(shipTypesCsv);
const ranks = lookup(ranksCsv);
const translate = (map, v) => (norm(v) ? map.get(norm(v)) ?? String(v).trim() : "");

const text = (v) => (v == null ? "" : String(v).trim());
// Ship and people's names are in capitals in the logbooks
const titleCase = (s) => text(s).toLowerCase().replace(/(^|[\s\-'.(/])(\p{L})/gu, (m, p, c) => p + c.toUpperCase());

// Wrap the parts of `str` matching any of `patterns` (the active keyword and
// search patterns from search.js) in <mark>. Returns nodes to append.
function highlight(str, patterns) {
  if (!patterns?.length || !str) return [str];
  const re = new RegExp(patterns.map((p) => `(?:${p.source})`).join("|"), "gi");
  const out = [];
  let last = 0;
  for (const m of str.matchAll(re)) {
    if (!m[0]) continue;                       // skip empty matches
    if (m.index > last) out.push(str.slice(last, m.index));
    out.push(el("mark", { class: "popup-match" }, m[0]));
    last = m.index + m[0].length;
  }
  if (last < str.length) out.push(str.slice(last));
  return out;
}

function companyName(code, nat) {
  const c = norm(code);
  if (!c) return "";
  const hit = companies.find((x) => x.codes.some((k) => norm(k) === c) && (!x.nationality || x.nationality === nat));
  return hit ? hit.label : text(code);
}

/**
 * view: the MapView. options:
 * - itemId: hosted logbook layer item
 * - locations: Map of location id -> {name, ...}
 * - onShowVoyage(track): the Show Voyage button was pressed
 * - onShowPlaceVoyages(locationId): a location's Show Voyages button was pressed
 * - getHighlights(): active keyword/search patterns (RegExp list); their
 *   matches are highlighted in the searched text (weather, sea, memos)
 */
export function createPopup(view, { itemId, locations, onShowVoyage, onShowPlaceVoyages, getHighlights = () => [] }) {
  const dateFormat = new Intl.DateTimeFormat(strings.dateLocale, { ...strings.dateFormat, timeZone: "UTC" });
  let layerUrl = null;
  const serviceUrl = async () => {
    if (!layerUrl) {
      const item = new PortalItem({ id: itemId });
      await item.load();
      layerUrl = `${item.url.replace(/\/$/, "")}/0`;
    }
    return layerUrl;
  };

  const card = el("div", { class: "popup", role: "dialog", hidden: true, tabindex: "-1" });
  document.body.append(card);
  let anchor = null;   // map point
  let request = 0;

  function place() {
    if (!anchor || card.hidden) return;
    const p = view.toScreen(anchor);
    const rect = view.container.getBoundingClientRect();
    if (!p || p.x < 0 || p.y < 0 || p.x > rect.width || p.y > rect.height) {
      card.style.visibility = "hidden";
      return;
    }
    card.style.visibility = "";
    const gap = 14, margin = 12;
    const w = card.offsetWidth, h = card.offsetHeight;
    const x = rect.left + p.x, y = rect.top + p.y;
    let left = x + gap;
    if (left + w > innerWidth - margin) left = x - gap - w;    // flip to the left of the point
    left = Math.max(margin, left);
    const top = Math.min(Math.max(margin, y - h / 2), innerHeight - margin - h);
    card.style.left = `${left}px`;
    card.style.top = `${Math.max(margin, top)}px`;
  }
  reactiveUtils.watch(() => view.extent, place);
  addEventListener("resize", place);

  function close() {
    request++;
    card.hidden = true;
    anchor = null;
  }
  card.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });

  function header(title, subtitle, nat) {
    const natInfo = nationalities.find((n) => n.value === nat);
    const closeBtn = el("button", { type: "button", class: "popup-close", "aria-label": strings.popup.close },
      el("calcite-icon", { icon: "x", scale: "s", "aria-hidden": "true" }));
    closeBtn.addEventListener("click", close);
    return el("header", { class: "popup-header" },
      el("div", { class: "popup-heading" },
        el("h2", { class: "popup-title" }, title),
        subtitle ? el("div", { class: "popup-date" }, subtitle) : null),
      flags[nat] ? el("img", { class: "popup-flag", src: flags[nat], alt: natInfo?.label ?? nat, width: 40, height: 40 }) : null,
      closeBtn);
  }

  function render(a, track) {
    const nat = text(a.Nationality);
    const marks = getHighlights();
    const hl = (str) => highlight(str, marks);
    let date = "";
    try {
      const d = new Date(Date.UTC(a.YR, a.MO - 1, a.DY));
      if (a.YR && a.MO && a.DY && d.getUTCDate() === Number(a.DY)) date = dateFormat.format(d);
      else if (a.YR) date = String(a.YR);
    } catch { date = text(a.YR); }

    const facts = [];
    const company = companyName(a.Company, nat);
    if (company) facts.push(el("p", { class: "popup-line popup-company" }, company));
    const type = translate(shipTypes, a.ShipType);
    if (type) facts.push(el("p", { class: "popup-line" }, type));

    const origin = locations.get(a.origin_location_id)?.name;
    const dest = locations.get(a.destination_location_id)?.name;
    if (origin || dest) {
      facts.push(el("div", { class: "popup-route" },
        el("span", { class: "popup-place", title: strings.popup.origin }, origin ? titleCase(origin) : "—"),
        el("span", { class: "popup-route-line", "aria-hidden": "true" }),
        el("span", { class: "popup-place popup-place-end", title: strings.popup.destination }, dest ? titleCase(dest) : "—")));
    }

    for (const i of [1, 2, 3]) {
      const name = titleCase(a[`Name${i}`]);
      const rank = translate(ranks, a[`Rank${i}`]);
      if (name || rank) facts.push(el("p", { class: "popup-line popup-observer" },
        rank ? el("span", { class: "popup-rank" }, rank) : null, rank && name ? " " : null, name));
    }

    const weather = [];
    if (text(a.Weather_en)) weather.push(el("p", { class: "popup-line" }, hl(text(a.Weather_en))));
    const wind = [text(a.AllWindDirections_en), text(a.AllWindForces_en)].filter(Boolean).join(", ");
    if (wind) weather.push(el("p", { class: "popup-line" }, el("span", { class: "popup-label" }, strings.popup.wind), " ", wind));
    if (text(a.StateSea_en)) {
      weather.push(el("p", { class: "popup-line" }, el("span", { class: "popup-label" }, strings.popup.sea), " ", hl(text(a.StateSea_en))));
    }

    const memos = MEMO_FIELDS.map((f) => text(a[f])).filter(Boolean);

    const sections = [];
    if (facts.length) sections.push(el("section", { class: "popup-section" }, facts));
    if (weather.length) {
      sections.push(el("section", { class: "popup-section" },
        el("h3", { class: "popup-section-title" }, strings.popup.weatherHeading), weather));
    }
    if (memos.length) {
      sections.push(el("section", { class: "popup-section" },
        el("ul", { class: "popup-memos" }, memos.map((m) => el("li", {}, hl(m))))));
    }
    let button = null;
    if (track != null) {
      button = el("button", { type: "button", class: "popup-voyage" }, strings.popup.showVoyage);
      button.addEventListener("click", () => onShowVoyage(track));
    }

    card.replaceChildren(header(titleCase(a.ShipName), date, nat),
      el("div", { class: "popup-body" }, sections, button ? el("div", { class: "popup-actions" }, button) : null));
    card.setAttribute("aria-label", titleCase(a.ShipName));
  }

  /** Show the entry `pointId` at map point `mapPoint`. attrs: the point's own attributes (shown while loading). */
  async function open(mapPoint, pointId, track, attrs = {}) {
    const mine = ++request;
    anchor = mapPoint;
    card.replaceChildren(header(titleCase(attrs.ship), "", attrs.nat),
      el("div", { class: "popup-body popup-status" }, strings.popup.loading));
    card.hidden = false;
    place();
    try {
      const url = await serviceUrl();
      const params = new URLSearchParams({
        objectIds: String(pointId), outFields: FIELDS.join(","), returnGeometry: "false", f: "json",
      });
      const res = await fetch(`${url}/query?${params}`).then((r) => r.json());
      if (mine !== request) return;
      const record = res.features?.[0]?.attributes;
      if (!record) throw new Error(res.error?.message || "No record");
      render(record, track);
    } catch (err) {
      if (mine !== request) return;
      console.error(err);
      card.replaceChildren(header(titleCase(attrs.ship), "", attrs.nat),
        el("div", { class: "popup-body popup-status" }, strings.popup.error));
    }
    place();
    card.focus({ preventScroll: true });
  }

  /** A location from the web map's location layers: name, modern name and a Show Voyages button. */
  function openLocation(mapPoint, attrs) {
    request++;
    anchor = mapPoint;
    const name = titleCase(attrs.common_name);
    const modern = text(attrs.modern_name);
    const button = el("button", { type: "button", class: "popup-voyage" }, strings.popup.showPlaceVoyages);
    button.addEventListener("click", () => onShowPlaceVoyages(attrs.location_id));
    card.replaceChildren(
      header(name, modern && modern.toUpperCase() !== name.toUpperCase() ? modern : "", null),
      el("div", { class: "popup-body" }, el("div", { class: "popup-actions" }, button)));
    card.setAttribute("aria-label", name);
    card.hidden = false;
    place();
    card.focus({ preventScroll: true });
  }

  return { open, openLocation, close, get isOpen() { return !card.hidden; } };
}
