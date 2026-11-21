// Filter state and the query that applies it to the points layer.
// Within a filter, choices combine with OR; across filters, with AND.
import { companies } from "./config/companies.js";

export function createState() {
  return {
    nationalities: new Set(),   // Nationality values
    companies: new Set(),       // company ids from companies.js
    origin: null,               // location_id
    destination: null,
    years: null,                // [from, to], or null for all years
    keywords: new Set(),        // keyword labels from keywords.csv
    text: "",                   // free-text search
  };
}

export const isActive = (s) =>
  s.nationalities.size > 0 || s.companies.size > 0 || s.origin != null || s.destination != null ||
  s.years != null || keywordActive(s);

export const keywordActive = (s) => s.keywords.size > 0 || s.text.trim().length > 0;

const quote = (v) => `'${String(v).replace(/'/g, "''")}'`;
const list = (vals) => vals.map(quote).join(", ");

// SQL where clause for every filter except keywords (those become object IDs).
export function buildWhere(s) {
  const parts = [];
  if (s.nationalities.size) parts.push(`nat IN (${list([...s.nationalities])})`);
  if (s.companies.size) {
    const ors = companies
      .filter((c) => s.companies.has(c.id))
      .map((c) => {
        const codes = `company IN (${list(c.codes)})`;
        return c.nationality ? `(${codes} AND nat = ${quote(c.nationality)})` : `(${codes})`;
      });
    parts.push(`(${ors.join(" OR ")})`);
  }
  if (s.origin != null) parts.push(`origin = ${Number(s.origin)}`);
  if (s.destination != null) parts.push(`dest = ${Number(s.destination)}`);
  if (s.years) parts.push(`year >= ${Number(s.years[0])} AND year <= ${Number(s.years[1])}`);
  return parts.length ? parts.join(" AND ") : "1=1";
}
