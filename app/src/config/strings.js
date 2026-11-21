// All interface text lives here. Placeholder (Lorem ipsum) text is marked
// TODO: replace. Data labels (nationalities, companies, keywords) are in the
// other files in this folder.
const LOREM = "Lorem ipsum dolor sit amet, consectetur adipiscing elit.";

export const strings = {
  pageTitle: "Logbook Explorer",
  panelTitle: "Explore",
  panelToggle: "Explore",                         // label for the collapse button on small screens
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

  // "{shown} of {total}" summary under the panel title
  count: (shown, total) => `${shown} / ${total}`,  // TODO: replace
  clearAll: "Lorem",                               // TODO: replace

  companyInfo: {                                   // TODO: replace; keyed by company id in companies.js
    default: LOREM,
  },
};
