// All interface text lives here. Placeholder (Lorem ipsum) text is marked
// TODO: replace. Data labels (nationalities, companies, keywords) are in the
// other files in this folder.

export const strings = {
  pageTitle: "Logbook Explorer",
  // Title over the panel, top left
  appTitle: "Logbook Explorer",
  appSubtitle: "1745–1855",
  panelTitle: "Explore",
  loading: "Loading...",                         // TODO: replace

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
  keywordSearchingText: "Loading...",           // TODO: replace (shown while search text loads)
  noMatches: "No matches found",                        // TODO: replace (combobox has no matches)

  // Summary under the panel title: log entries and voyages matching the filters
  // (numbers; singular wording when the count is 1)
  count: (entries, voyages) =>
    `${entries.toLocaleString()} ${entries === 1 ? "log entry" : "log entries"} | `
    + `${voyages.toLocaleString()} ${voyages === 1 ? "Voyage" : "Voyages"}`,
  // Data credit under the summary counts (creditUrl: optional link)
  credit: "Data: CLIWOC 2.1, Climatological Database for the World's Oceans (KNMI)",
  creditUrl: null,
  clearAll: "Clear filters",                               // TODO: replace

  // Point tooltip: ship name over the date, formatted with these Intl options
  tooltipLabel: "Tooltip",                     // TODO: replace (accessible name for the tooltip)
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

  // Info panel: open on launch, and again from the info button by the map buttons
  info: {
    button: "About this map",                      // accessible name of the info button
    heading: "About the logbooks",
    description: "The Climatological Database for the World's Oceans (CLIWOC) gathers more than "
      + "280,000 entries transcribed from the logbooks of "
      + "European sailing ships during the 18th and 19th centuries, recording each ship's position alongside the wind, weather and sea, and "
      + "notes on life on board.",
    howToHeading: "How to use the map",
    steps: [
      "Each line is a ship's voyage, coloured by the ship's nationality. Zoom in to see the daily log entries along it.",
      "Hover over a log entry for the ship and date, and click it to read the full entry.",
      "Filter the map with the Explore panel: nationality, voyage origin and destination, company, keywords and dates.",
      "Click Show Voyage in an entry to follow that ship's whole voyage.",
      "Click a port or place to see every voyage that sailed from or to it.",
      "Use Back to map to return to your filters.",
    ],
    close: "Start exploring",
  },

  // Company info button: opens the company's Wikipedia page in a new tab
  companyLink: (company) => `${company} on Wikipedia (opens in a new tab)`,
};
