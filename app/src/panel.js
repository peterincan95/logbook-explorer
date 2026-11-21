// The Explore panel: one collapsible block per filter.
import { strings } from "./config/strings.js";
import { nationalities } from "./config/nationalities.js";
import { companies } from "./config/companies.js";
import { isActive } from "./filters.js";

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style" && typeof v === "object") {
      for (const [prop, val] of Object.entries(v)) node.style.setProperty(prop, val);
    }
    else if (typeof v === "object" || (k in node && typeof v !== "string")) node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  node.append(...children.flat().filter((c) => c != null));
  return node;
};

function block(heading, ...content) {
  return el("calcite-block", { heading, expandable: true, class: "filter-block" },
    el("div", { class: "block-content" }, ...content));
}

// A toggle chip (aria-pressed). Selected chips show a close icon, as in the mockups.
function chip(label, { pressed, onToggle, className = "", style } = {}) {
  const icon = el("calcite-icon", { icon: "x-circle-f", scale: "s", class: "chip-close", "aria-hidden": "true" });
  const btn = el("button", { type: "button", class: `chip ${className}`, style, "aria-pressed": String(!!pressed) },
    el("span", { class: "chip-label" }, label), icon);
  btn.addEventListener("click", () => {
    const on = btn.getAttribute("aria-pressed") !== "true";
    btn.setAttribute("aria-pressed", String(on));
    onToggle(on);
  });
  return btn;
}

function locationCombobox(id, items, countKey, onSelect) {
  const box = el("calcite-combobox", {
    id, "selection-mode": "single", placeholder: strings.searchPlaceholder, "placeholder-icon": "search",
    "max-items": "8", scale: "m", label: id, class: "location-search",
  });
  for (const loc of [...items].filter((l) => l[countKey] > 0).sort((a, b) => b[countKey] - a[countKey])) {
    box.append(el("calcite-combobox-item", {
      value: String(loc.id), heading: loc.name, label: loc.name,
      description: loc.modern && loc.modern.toUpperCase() !== loc.name ? loc.modern : null,
      metadata: { names: loc.names.join(" ") },
    }));
  }
  box.addEventListener("calciteComboboxChange", () => {
    const v = box.value;
    onSelect(v ? Number(Array.isArray(v) ? v[0] : v) : null);
  });
  return box;
}

/**
 * Build the panel into `root`.
 * - state: filter state from filters.js (mutated here)
 * - onChange(): called after any filter changes
 * - locations: from locations.json
 * - keywords: [{label, words}]
 * - years: {min, max, histogram: [[year, count], ...]}
 * - onKeywordOpen(): called when the keyword block is first opened (to preload search text)
 */
export function buildPanel(root, { state, onChange, locations, keywords, years, onKeywordOpen }) {
  const count = el("span", { class: "panel-count", "aria-live": "polite" });
  const clear = el("button", { type: "button", class: "panel-clear", hidden: true }, strings.clearAll);
  const toggle = el("button", { type: "button", class: "panel-toggle", "aria-expanded": "true", "aria-label": strings.panelToggle },
    el("calcite-icon", { icon: "chevron-up", scale: "s" }));
  const header = el("header", { class: "panel-header" },
    el("div", { class: "panel-title-row" }, el("h1", { class: "panel-title" }, strings.panelTitle), toggle),
    el("div", { class: "panel-meta" }, count, clear));

  const changed = () => {
    clear.hidden = !isActive(state);
    onChange();
  };

  // Nationality
  const natChips = nationalities.map((n) =>
    chip(n.label, {
      className: "chip-nat", style: { "--nat-color": n.chip },
      onToggle: (on) => { on ? state.nationalities.add(n.value) : state.nationalities.delete(n.value); changed(); },
    }));
  const natBlock = block(strings.sections.nationality, el("div", { class: "chip-row" }, natChips));

  // Voyage origin / destination
  const origin = locationCombobox("origin-search", locations, "origin", (id) => { state.origin = id; changed(); });
  const dest = locationCombobox("destination-search", locations, "dest", (id) => { state.destination = id; changed(); });
  const voyageBlock = block(strings.sections.voyage,
    el("label", { class: "field-label", for: "origin-search" }, strings.voyage.origin), origin,
    el("label", { class: "field-label", for: "destination-search" }, strings.voyage.destination), dest);

  // Company: chip with an info button that opens a popover
  const companyChips = companies.map((c) => {
    const infoId = `info-${c.id}`;
    const info = el("button", { type: "button", class: "chip-info", id: infoId, "aria-label": c.label },
      el("calcite-icon", { icon: "information-f", scale: "s", "aria-hidden": "true" }));
    const toggleChip = chip(c.label, {
      className: "chip-company",
      onToggle: (on) => { on ? state.companies.add(c.id) : state.companies.delete(c.id); changed(); },
    });
    const pop = el("calcite-popover", { "reference-element": infoId, label: c.label, "auto-close": true, closable: true, placement: "top" },
      el("p", { class: "popover-text" }, strings.companyInfo[c.id] ?? strings.companyInfo.default));
    return el("span", { class: "company-chip" }, info, toggleChip, pop);
  });
  const companyBlock = block(strings.sections.company, el("div", { class: "chip-row" }, companyChips));

  // Keyword: free text plus the curated chips
  const search = el("calcite-input", {
    type: "search", placeholder: strings.searchPlaceholder, icon: "search", clearable: true,
    label: strings.sections.keyword, class: "keyword-search",
  });
  let timer;
  search.addEventListener("calciteInputInput", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.text = search.value || ""; changed(); }, 300);
  });
  const kwChips = keywords.map((k) =>
    chip(k.label, {
      className: "chip-keyword",
      onToggle: (on) => { on ? state.keywords.add(k.label) : state.keywords.delete(k.label); changed(); },
    }));
  const keywordBlock = block(strings.sections.keyword, search, el("div", { class: "chip-row" }, kwChips));
  keywordBlock.addEventListener("calciteBlockExpand", () => onKeywordOpen?.(), { once: true });

  // Date range (years), with a histogram of points per year
  const slider = el("calcite-slider", {
    min: years.min, max: years.max, "min-value": years.min, "max-value": years.max, step: 1,
    "label-handles": true, label: strings.sections.dates, class: "year-slider", "group-separator": false,
  });
  slider.histogram = years.histogram;
  let yearTimer;
  slider.addEventListener("calciteSliderInput", () => {
    clearTimeout(yearTimer);
    yearTimer = setTimeout(() => {
      const lo = slider.minValue, hi = slider.maxValue;
      state.years = lo <= years.min && hi >= years.max ? null : [lo, hi];
      changed();
    }, 120);
  });
  const dateBlock = block(strings.sections.dates, slider);

  const blocks = [natBlock, voyageBlock, companyBlock, keywordBlock, dateBlock];
  const body = el("div", { class: "panel-body" }, blocks);
  root.append(header, body);

  // Only one filter block open at a time.
  for (const b of blocks) {
    b.addEventListener("calciteBlockExpand", () => {
      for (const other of blocks) if (other !== b) other.expanded = false;
    });
  }

  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(open));
    root.classList.toggle("collapsed", !open);
  });

  clear.addEventListener("click", () => {
    state.nationalities.clear();
    state.companies.clear();
    state.keywords.clear();
    state.origin = state.destination = state.years = null;
    state.text = "";
    root.querySelectorAll(".chip[aria-pressed='true']").forEach((b) => b.setAttribute("aria-pressed", "false"));
    for (const box of [origin, dest]) {
      box.selectedItems.forEach((item) => { item.selected = false; });
      box.value = "";
    }
    search.value = "";
    slider.minValue = years.min;
    slider.maxValue = years.max;
    changed();
  });

  return {
    setCount(shown, total) { count.textContent = strings.count(shown.toLocaleString(), total.toLocaleString()); },
    setSearching(on) { search.loading = on; },
  };
}
