// Company chips. Each chip matches logbook rows whose Company field is one of
// `codes`, optionally limited to one Nationality (MAR and ADM appear in both
// Dutch and French logbooks). The info text for each id is in strings.js.
// Rows with no company recorded have no chip.
export const companies = [
  { id: "royal-navy", label: "Royal Navy", codes: ["RN", "ROYAL NAVY"] },
  { id: "eic", label: "East India Company", codes: ["EIC"] },
  { id: "hbc", label: "Hudson's Bay Company", codes: ["HUDSON BAY COMPANY"] },
  { id: "merchant-navy", label: "Merchant Navy", codes: ["MERCHANT NAVY"] },
  { id: "dutch-navy", label: "Royal Netherlands Navy", codes: ["MAR"], nationality: "DUTCH" },
  { id: "dutch-admiralty", label: "Dutch Admiralty", codes: ["ADM"], nationality: "DUTCH" },
  { id: "voc", label: "VOC", codes: ["VOC", "VOC-Z"] },
  { id: "wic", label: "WIC", codes: ["WIC"] },
  { id: "mcc", label: "MCC", codes: ["MCC"] },
  { id: "dutch-whalers", label: "Dutch whalers", codes: ["WHA"] },
  {
    id: "dutch-private", label: "Dutch private ships",
    codes: ["MER", "PARTICULIER", "A. HOBOKEN, ROTTERDAM", "A. VAN HOBOKEN & ZN. TE ROTTERDAM.",
            "H. V. RIJCKEVORSEL, ROTTERDAM", "THOMAS BROUW EN ZN."],
  },
  { id: "french-navy", label: "French Navy", codes: ["MAR", "ADM"], nationality: "FRENCH" },
  { id: "swedish-eic", label: "Swedish EIC", codes: ["SWEDISH EAST INDIA COMPANY"] },
  { id: "danish-eic", label: "Danish EIC", codes: ["OIC"] },
];
