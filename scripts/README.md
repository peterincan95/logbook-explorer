# Data prep scripts

## Translation of memo and weather fields

`translate_logs.py` adds an English `<Field>_en` column next to each of these fields and writes the result to `data/cliwoc_points_en.csv`. The original CSV is never modified.

- **Memo fields:** LifeOnBoard, EncRem, CargoMemo, ShipAndRigMemo, BiologyMemo, WarsAndFightsMemo, OtherRem, OtherShipInformation
- **Weather fields:** Weather, AllWindForces, StateSea, PrecipitationDescriptor, ShapeClouds, Clearness, AllWindDirections, DirClouds

### How each value is handled

| Case | Handling |
|---|---|
| Symbol codes (`W00`, `V04` …) and plain numbers | Copied unchanged |
| Compass directions | Converted by rules in `compass.py` (Dutch O = E, Z = S; Spanish/French O = W). Only unparseable leftovers go to the model |
| Dutch / Spanish / French text | Translated by Claude Sonnet 5.5, in sentence case |
| Text from English logbooks | Sent to the model for re-casing only. If the model changes any word, the casing is done by a simple rule instead (`recase_rule`) |

Every unique (language, field, text) value is translated once and stored in `data/translation_cache.sqlite`. Re-running a step never re-sends a phrase that is already in the cache. The prompt and glossary are in `translation_prompt.py`.

### Running it

```bash
pip install -r requirements.txt
python scripts/translate_logs.py extract        # find unique phrases, apply rules (free)
python scripts/translate_logs.py pilot --n 300  # translate a sample -> data/translation_pilot_review.csv
python scripts/translate_logs.py submit         # send everything pending as one Message Batch (half price)
python scripts/translate_logs.py collect --wait # poll until the batch ends, store results
python scripts/translate_logs.py write          # build data/cliwoc_points_en.csv
python scripts/translate_logs.py status         # progress and API spend at any point
```

If the pilot shows problems, edit `translation_prompt.py`. To re-translate the pilot phrases with the new prompt, run this first:

```bash
python -c "import sqlite3; db=sqlite3.connect('data/translation_cache.sqlite'); db.execute(\"UPDATE phrases SET status='pending', en=NULL, attempts=0 WHERE method IN ('llm','recase','recase_rule')\"); db.commit()"
```

## Setting up an Anthropic API key (Windows)

1. Sign in or create an account at **https://platform.claude.com**. This is the developer console; it's separate from a claude.ai chat subscription.
2. Under **Billing**, add a payment method and buy some prepaid credits. $25 is plenty for this job.
3. Recommended: under **Limits**, set a monthly spend limit.
4. Go to **API keys → Create key**, name it (e.g. `cliwoc-explorer`) and copy it. It's shown only once.
5. Save it as a user environment variable. Run this in PowerShell, pasting your key in place of the placeholder:

   ```powershell
   [Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "paste-your-key-here", "User")
   ```

6. Close and reopen your terminal (and restart the Claude app if you run the scripts from there) so the variable is picked up.
7. Check that it works. This call is free:

   ```bash
   python -c "import anthropic; print(anthropic.Anthropic().models.retrieve('claude-sonnet-5-5').display_name)"
   ```

Never paste the key into code, chat or a file inside the project folder. The SDK reads it from the environment automatically.

## Place table and geocoding

```bash
python scripts/build_place_table.py          # data/voyage_places.csv: every name in VoyageFrom, VoyageTo, AnchorPlace
python scripts/geocode_places.py interpret   # Claude: place type, modern name, country, search queries, rough position (needs ANTHROPIC_API_KEY)
python scripts/geocode_places.py lookup      # GeoNames (set GEONAMES_USERNAME; throttled to 950/hour), Nominatim fallback
python scripts/geocode_places.py resolve     # score candidates, write outputs (no network)
python scripts/geocode_places.py status
```

Everything is cached in `data/geocode_cache.sqlite`, so each step can be re-run or resumed at no cost.

Outputs:
- `data/voyage_places_geocoded.csv`: one row per place as written, joinable to the logbook on the place columns. `precision` is exact / approximate / area (country or region centroid) / none (at sea or not found). `source` is geonames, nominatim, claude (no confident gazetteer match) or override.
- `data/voyage_places_review.csv`: flagged groups, most-used first, with `flag_reason`.

To correct a place, add a row to `data/place_overrides.csv` and re-run `resolve`:
- `place`: the name as written. `applies_to` = `group` covers every spelling in its group (DOWNS, THE DOWNS); blank matches that exact spelling only (use this for names with "?", whose group may hold a different place).
- `lat`, `lon`: new coordinates, or blank to keep and confirm the automatic ones.
- `place_type`: the usual types, plus `not_a_place` (generic word, ship name, fleet position) and `itinerary` (several stops), which never get coordinates.
- `modern_name`, `country_code`, `precision`, `confidence` (defaults to high), `note`: optional.

## Locations (one point per place)

```bash
python scripts/build_locations.py
```

Merges every place name with identical coordinates into one location (CADIZ, CÁDIZ, CADIX; TABLE BAY, KAAPSTAD); names without coordinates are merged by folded spelling. Usage counts are recomputed per location from the logbook. `build_gdb.py` runs this automatically.

- `data/locations.csv`: one row per location. `common_name` is the most-used spelling, `names_as_written` lists every spelling (separated by " | ").
- `data/place_to_location.csv`: every place name as written → `location_id`.

Location IDs are stable across rebuilds: `data/location_ids.json` records each place name's ID, and a location keeps the ID most of its names already had, even if its coordinates or spellings change. If locations merge, the larger keeps its ID; if one splits, the larger part keeps it. New IDs continue from the highest ever issued, so a retired ID is never reused. Keep `location_ids.json` with the project (don't delete it), or IDs will be renumbered.

## File geodatabase for ArcGIS Pro

Needs ArcGIS Pro's Python (arcpy). Rebuilds `gis/cliwoc_explorer.gdb` from the CSVs:

```bash
"/c/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe" scripts/build_gdb.py
```

- `locations`: one point per location; `location_id` is the key. Built from `data/locations.csv` (see below). Locations without coordinates keep an empty geometry.
- `logbook_points`: every row of `cliwoc_points_en.csv`, plus `origin_location_id`, `destination_location_id`, `anchor_location_id` (join to `locations.location_id`) and `obs_date` (from YR, MO, DY, HR). Rows without a position keep an empty geometry.
- Field aliases on `logbook_points` come from the data dictionary (first clause of each description; `_en` fields get "(English)"). To refresh only the aliases on an existing geodatabase, add `--aliases-only`.
- Relationship classes `rel_location_origin`, `rel_location_destination`, `rel_location_anchor`.

Re-run it after changing translations or place overrides.

## Web app data

```
python scripts/build_web_data.py
```

Writes the slim files the web app loads into `app/public/data/`: `points.csv` (positioned points with only the fields the filters use), `search.tsv` (English memo and weather text for keyword search) and `locations.json` (origins and destinations with all their spellings). Re-run it after changing the logbook, places or locations (run `build_locations.py` first if places changed), then rebuild and redeploy the app. See `app/README.md`.
