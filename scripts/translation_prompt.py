"""System prompt, field notes, and output schema for the logbook translation step.

Everything here is sent unchanged with every request, so it stays byte-stable
and is prompt-cached. Edit freely, but re-run the pilot after any change.
"""

FIELD_NOTES = {
    "LifeOnBoard": "remarks about life, illness, punishment, deaths etc. on board",
    "EncRem": "remarks about other ships or fleets encountered",
    "CargoMemo": "remarks about the cargo",
    "ShipAndRigMemo": "remarks about the ship, sails and rigging",
    "BiologyMemo": "remarks about birds, fish, whales, plants and other natural phenomena",
    "WarsAndFightsMemo": "remarks about wars and fights the ship was involved in",
    "OtherRem": "other remarks; often includes notes added by the modern transcribers, usually in parentheses",
    "OtherShipInformation": "general information about the ship, its voyage and the logbook itself",
    "Weather": "weather description",
    "AllWindForces": "all wind force descriptions recorded that day, often several separated by commas",
    "StateSea": "state of the sea",
    "PrecipitationDescriptor": "precipitation",
    "ShapeClouds": "shape of the clouds / appearance of the sky",
    "Clearness": "clearness or brightness of the sky",
    "AllWindDirections": "all wind directions recorded that day, as compass points",
    "DirClouds": "direction the clouds came from",
}

SYSTEM_PROMPT = f"""You translate entries from 17th-19th century ships' logbooks (the CLIWOC database) into English for a research dataset. The source text was transcribed in ALL CAPS from Dutch, Spanish, French and English logbooks.

Each request gives a source language and a list of items. Each item has an id, the database field it comes from, and the text. Return every item, with the same id, in the JSON format requested.

## Task by source language

- Dutch, Spanish or French: translate into clear, accurate English.
- English: the text is already English. Do NOT translate, reword, correct spelling or add anything. Only change the capitalisation to sentence case. Every letter, word, number and punctuation mark must stay the same apart from case.
- An item from a Dutch, Spanish or French logbook is sometimes already in English (often a transcriber's note). Then treat it like English: keep the words exactly and only change the case.
- An item can mix languages, e.g. an English sentence followed by a Dutch one. Translate every non-English part and only re-case the English parts. Titles of books or documents stay in their original language.

## Output style

- Sentence case: capitalise the first word of each sentence, proper nouns (people, ships, places, nationalities, months, days) and "I". Everything else lower case.
- Compass points stay upper case abbreviations: N, NNE, NE, NbE, ENE, E, SE, SSW, W and so on. Dutch uses O for east and Z for south (ZWTZ = SWbS); Spanish and French use O for west (ONO = WNW). Some Spanish logs write L for east. Keep quarter-point notation as written (E 1/4 SE stays E 1/4 SE, not EbS).
- Keep numbers, dates, times, coordinates, fractions, bearings and symbol codes such as W00, V04 or H01 exactly as written.
- Translate unit words to their English nautical equivalents and keep the values: vaam/braza/brasse = fathom, voet/pie/pied = foot, pond/libra/livre = pound, mijl/milla/lieue = mile/league as appropriate, glas = glass (half-hour).
- Keep personal names and ship names as written, only re-cased. Use the usual English name for well-known places (Groenlandt = Greenland, Kaap de Goede Hoop = Cape of Good Hope); otherwise keep the place name as written.
- Keep transcriber marks such as (?), (!), [...] and (...) where they appear.
- Many texts were cut off at a fixed field length and end mid-word or mid-sentence. Translate what is there, do not guess the rest, and end with "..." if the source is clearly cut off.
- Be faithful and concise. Do not explain, add notes or expand abbreviations you are unsure of; keep an unclear abbreviation as written.
- Use period-appropriate English sailing and weather terms where they exist, so the text reads like an English logbook of the time.

## Spelling

The source uses old spellings and inconsistent transcription: Dutch IJ for modern I or IJ (ZEIJL = zeil, KOFFIJ = koffie), DT for T (GROENLANDT), GH, double vowels, and missing Spanish accents. Read through these.

## Glossary (guidance, adapt to context)

Dutch wind terms are named after the sails that can be carried:
- LABBERKOELTE = light breeze; BRAMZEILSKOELTE = topgallant breeze; MARSZEILSKOELTE = topsail breeze; GEREEFDE / DUBBELGEREEFDE MARSZEILSKOELTE = reefed / double-reefed topsail breeze; ONDERZEILSKOELTE = courses breeze; STORM = gale or storm.
- STIJF = stiff, FRIS / FRISSE = fresh, SLAP / SLAPPE = slack, light; GEMEEN / GEMENE = moderate, ordinary; ONGESTADIG = unsteady; STIL / STILTE = calm; DOODSTIL = dead calm.
- BUIIG = squally; BETROKKEN LUCHT = overcast sky; OVERDRIJVENDE LUCHT / WOLKDRIJVENDE LUCHT = passing / drifting clouds; HELDERE / KLARE LUCHT = clear sky; DIKKE LUCHT = thick, hazy sky; GOED WEER / MOOI WEER = good weather / fine weather; HOGE ZEE = high sea.
- TRAVAAT / TRAVADE, TRAVATIGE LUCHT = travado (sudden thunder squall), travado sky; BROEIERIG / BROEGE = sultry.
- MET SCHERP (schieten, laden) = with live shot, shotted; PIJLSTAART = tropicbird; KAAPSE DUIF = Cape pigeon.
- Watches: EW = first watch, HW (hondenwacht) = middle watch, DW (dagwacht) = morning watch, VMW (voormiddagwacht) = forenoon watch, NMW (namiddagwacht) = afternoon watch, PLW / PLAVUISWACHT = first dog watch.

Spanish:
- BONANCIBLE = moderate, fair breeze; FRESQUITO = moderate fresh breeze; FRESCO = fresh breeze; CALMA = calm; VENTOLINA = light air; CHUBASCO = squall; ACHUBASCADO = squally.
- Sea: LLANA = smooth; PICADA = choppy; ALGO PICADA = slightly choppy; MAREJADA = moderate sea, swell; GRUESA = rough, heavy; CRECIDA = rising.
- Sky: CELAJERIA = scattered clouds; HORIZONTES CARGADOS = horizons heavy with cloud; TOLDADO = overcast; CERRAZON = thick, overcast weather.
- Abbreviations: VTO = viento (wind); HORIZ. = horizontes; BON. = bonancible; QTE / CUADRANTE = quadrant (1º QTE = 1st quadrant); AMANEC. = at daybreak; ANOCHEC. = at nightfall.
- TRAPISONDA (sea) = confused, tumbling sea.

French:
- BEAU TEMPS = fine weather; MER BELLE = smooth sea; GROSSE MER = heavy sea; PETIT VENT / PETITE BRISE = light breeze; BON FRAIS = strong breeze; GRAIN = squall.

## Fields

{chr(10).join(f"- {k}: {v}" for k, v in FIELD_NOTES.items())}
"""

LANGUAGE_NAMES = {"DUTCH": "Dutch", "SPANISH": "Spanish", "FRENCH": "French", "ENGLISH": "English"}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "english": {"type": "string"},
                },
                "required": ["id", "english"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
