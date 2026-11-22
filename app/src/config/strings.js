// All interface text lives here. Placeholder (Lorem ipsum) text is marked
// TODO: replace. Data labels (nationalities, companies, keywords) are in the
// other files in this folder.
const LOREM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit.";

export const strings = {
  pageTitle: "Logbook Explorer",
  panelTitle: "Explore",
  loading: "Lorem ipsum…",                         // TODO: replace

  sections: {
    nationality: "Nationality",
    voyage: "Voyage Origin/Destination",
    company: "Company",
    keyword: "Keyword",
    dates: "Date range",
  },

  voyage: {
    origin: "Origin:",
    destination: "Destination:",
  },
  searchPlaceholder: "Search",
  keywordSearchingText: "Lorem ipsum…",           // TODO: replace (shown while search text loads)
  noMatches: "Lorem ipsum",                        // TODO: replace (combobox has no matches)

  // Summary under the panel title: log entries and voyages matching the filters
  count: (entries, voyages) => `${entries} log entries | ${voyages} Voyages`,
  clearAll: "Lorem",                               // TODO: replace

  // Point tooltip: ship name over the date, formatted with these Intl options
  tooltipLabel: "Lorem ipsum",                     // TODO: replace (accessible name for the tooltip)
  dateLocale: "en-GB",
  dateFormat: { day: "numeric", month: "long", year: "numeric" },

  companyInfo: {                                   // TODO: replace; keyed by company id in companies.js
    default: LOREM,
  },
};
