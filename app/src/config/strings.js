// All interface text lives here. Placeholder (Lorem ipsum) text is marked
// TODO: replace. Data labels (nationalities, companies, keywords) are in the
// other files in this folder.
const LOREM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit.";

export const strings = {
  pageTitle: "Logbook Explorer",
  // Title over the panel, top left
  appTitle: "Logbook Explorer",
  appSubtitle: "1745–1855",
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
  // (numbers; singular wording when the count is 1)
  count: (entries, voyages) =>
    `${entries.toLocaleString()} ${entries === 1 ? "log entry" : "log entries"} | `
    + `${voyages.toLocaleString()} ${voyages === 1 ? "Voyage" : "Voyages"}`,
  // Data credit under the summary counts (creditUrl: optional link)
  credit: "Data: CLIWOC 2.1, Climatological Database for the World's Oceans (KNMI)",
  creditUrl: null,
  clearAll: "Lorem",                               // TODO: replace

  // Point tooltip: ship name over the date, formatted with these Intl options
  tooltipLabel: "Lorem ipsum",                     // TODO: replace (accessible name for the tooltip)
  dateLocale: "en-GB",
  dateFormat: { day: "numeric", month: "long", year: "numeric" },

  // Popup for a clicked log entry
  popup: {
    close: "Close",                                // accessible name of the close button
    loading: "Loading log entry…",                 // while the entry loads
    error: "This log entry couldn't be loaded.",   // entry couldn't be loaded
    origin: "Origin",
    destination: "Destination",
    weatherHeading: "Weather Observations",
    wind: "Wind:",                                 // label before wind direction and force
    sea: "Sea:",                                   // label before state of the sea
    showVoyage: "Show Voyage",
    showPlaceVoyages: "Show Voyages",              // location popup: voyages from or to the place
  },
  // Shown in the panel header while one voyage is shown
  voyageBack: "Back to map",                       // button back to the filtered map

  companyInfo: {                                   // TODO: replace; keyed by company id in companies.js
    default: LOREM,
  },
};
