// Company chips. Each chip matches logbook rows whose Company field is one of
// `codes`, optionally limited to one Nationality (MAR and ADM appear in both
// Dutch and French logbooks). `wiki`: the Wikipedia article the chip's info
// button opens in a new tab.
// Rows with no company recorded have no chip.
export const companies = [
  { id: "royal-navy", label: "Royal Navy", codes: ["RN", "ROYAL NAVY"],
    wiki: "https://en.wikipedia.org/wiki/Royal_Navy" },
  { id: "eic", label: "East India Company", codes: ["EIC"],
    wiki: "https://en.wikipedia.org/wiki/East_India_Company" },
  { id: "hbc", label: "Hudson's Bay Company", codes: ["HUDSON BAY COMPANY"],
    wiki: "https://en.wikipedia.org/wiki/Hudson%27s_Bay_Company" },
  { id: "merchant-navy", label: "Merchant Navy", codes: ["MERCHANT NAVY"],
    wiki: "https://en.wikipedia.org/wiki/Merchant_Navy_(United_Kingdom)" },
  { id: "dutch-navy", label: "Royal Netherlands Navy", codes: ["MAR"], nationality: "DUTCH",
    wiki: "https://en.wikipedia.org/wiki/Royal_Netherlands_Navy" },
  { id: "dutch-admiralty", label: "Dutch Admiralty", codes: ["ADM"], nationality: "DUTCH",
    wiki: "https://en.wikipedia.org/wiki/Dutch_States_Navy" },
  { id: "voc", label: "VOC", codes: ["VOC", "VOC-Z"],
    wiki: "https://en.wikipedia.org/wiki/Dutch_East_India_Company" },
  { id: "wic", label: "WIC", codes: ["WIC"],
    wiki: "https://en.wikipedia.org/wiki/Dutch_West_India_Company" },
  { id: "mcc", label: "MCC", codes: ["MCC"],
    wiki: "https://en.wikipedia.org/wiki/Middelburgsche_Commercie_Compagnie" },
  { id: "dutch-whalers", label: "Dutch whalers", codes: ["WHA"],
    wiki: "https://en.wikipedia.org/wiki/Whaling_in_the_Netherlands" },
  {
    id: "dutch-private", label: "Dutch private ships",
    codes: ["MER", "PARTICULIER", "A. HOBOKEN, ROTTERDAM", "A. VAN HOBOKEN & ZN. TE ROTTERDAM.",
            "H. V. RIJCKEVORSEL, ROTTERDAM", "THOMAS BROUW EN ZN."],
    wiki: "https://en.wikipedia.org/wiki/Economic_history_of_the_Netherlands_(1500%E2%80%931815)" },
  { id: "french-navy", label: "French Navy", codes: ["MAR", "ADM"], nationality: "FRENCH",
    wiki: "https://en.wikipedia.org/wiki/French_Navy" },
  { id: "swedish-eic", label: "Swedish EIC", codes: ["SWEDISH EAST INDIA COMPANY"],
    wiki: "https://en.wikipedia.org/wiki/Swedish_East_India_Company" },
  { id: "danish-eic", label: "Danish EIC", codes: ["OIC"],
    wiki: "https://en.wikipedia.org/wiki/Danish_Asiatic_Company" },
];
