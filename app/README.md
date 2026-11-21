# CLIWOC Explorer web app

A map of every positioned CLIWOC logbook observation (260,639 points), with
filters for nationality, voyage origin and destination, company, keywords and
date range. Built with Vite, the ArcGIS Maps SDK for JavaScript and Calcite
components. It is a static site: there is no server or hosted layer, and all
filtering runs in the browser.

## Run locally

```
cd app
npm install
npm run dev        # http://localhost:5176
npm run build      # production build in app/dist
npm run preview    # serve the build
```

## Data

The files in `public/data/` are built from the project data by
`scripts/build_web_data.py` (run from the project root):

| File | Contents | Loaded |
|---|---|---|
| `points.csv` | position, nationality, company, origin/destination location IDs and year for each point. `point_id` is the row number in `data/cliwoc_points_en.csv` and the OBJECTID in the geodatabase | at start |
| `search.tsv` | lowercased English memo and weather text, keyed by row number in points.csv | when the keyword panel is first opened |
| `locations.json` | locations used as an origin or destination, with every spelling as written | at start |

Rebuild them after changing the logbook, the places or the locations.

## Configuration (`src/config/`)

| File | What to edit |
|---|---|
| `strings.js` | All interface text. Placeholder text is marked `TODO: replace`, including the company info text |
| `nationalities.js` | Nationality chips: label, chip colour and map point colour |
| `companies.js` | Company chips: which Company codes each chip covers, optionally limited to one nationality |
| `keywords.csv` | The keyword chips. `words` is a `\|`-separated list; `*` matches the rest of a word (`whal*`), and a phrase must appear as written (`put in irons`). Matching ignores case and starts at the beginning of a word, so `ice` doesn't match "notice" |
| `map.js` | Basemap, starting view, point size and opacity |

Keyword chips are matched in the browser, so editing `keywords.csv` only needs
a rebuild and redeploy of the app.

## How filtering works

- Within a filter, choices combine with OR (England or France). Across
  filters they combine with AND (England, and Royal Navy, and 1780–1800).
- Typed keyword text and the keyword chips are one filter, so they also
  combine with OR.
- Non-matching points are hidden.

## Deploy to GitHub Pages

`.github/workflows/deploy-pages.yml` builds and publishes the app on every
push to `main`. One-time setup:

1. Create a GitHub repository and push this project to it (the `.gitignore`
   leaves out the large logbook CSVs, caches and the geodatabase).
2. In the repository's **Settings → Pages**, set **Source** to **GitHub Actions**.
3. Push to `main`. The site appears at `https://<user>.github.io/<repo>/`.

The build uses relative paths, so it works under any repository name.
