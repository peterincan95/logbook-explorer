// Keyword and free-text search over the English memo and weather text.
// search.tsv (object ID <tab> lowercased text) is fetched the first time a
// search runs, then every search scans it in memory.

let index = null;

export function loadSearchIndex(url) {
  index ??= fetch(url)
    .then((r) => {
      if (!r.ok) throw new Error(`${url}: ${r.status}`);
      return r.text();
    })
    .then((text) => {
      const ids = [];
      const texts = [];
      for (const line of text.split("\n")) {
        const tab = line.indexOf("\t");
        if (tab > 0) {
          ids.push(Number(line.slice(0, tab)));
          texts.push(line.slice(tab + 1));
        }
      }
      return { ids, texts };
    });
  return index;
}

const escape = (s) => s.replace(/[.+?^${}()|[\]\\]/g, "\\$&");

// One term: words separated by spaces must appear in order; * matches the
// rest of a word ("whal*" finds whale, whales, whaling). Terms match from the
// start of a word, so "ice" does not match "notice".
function termSource(term) {
  return term
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .map((w) => escape(w).replace(/\*/g, "\\w*"))
    .join("\\s+");
}

// "whale*|whaling" (keywords.csv) -> one regular expression.
export function compileWords(words) {
  const terms = words.split("|").map(termSource).filter(Boolean);
  return terms.length ? new RegExp(`\\b(?:${terms.join("|")})\\b`) : null;
}

// Free text typed by the user: a phrase that must start at a word boundary
// and may end mid-word, so typing "whal" already finds whales.
export function compileQuery(query) {
  const src = termSource(query);
  return src ? new RegExp(`\\b${src}`) : null;
}

// Object IDs of points whose text matches any of the patterns.
export function matchIds({ ids, texts }, patterns) {
  const out = [];
  for (let i = 0; i < texts.length; i++) {
    const t = texts[i];
    if (patterns.some((p) => p.test(t))) out.push(ids[i]);
  }
  return out;
}
