"""Rule-based conversion of logbook compass directions to English abbreviations.

Dutch logbooks use O (oost) for east and Z (zuid) for south, with T (ten) for
"by" (ZWTZ = SW by S). Spanish and French use O (oeste/ouest) for west.
Returns None when a string contains anything the rules don't recognise, so
the caller can send it to the model instead.
"""
import re

LETTERS = {
    "DUTCH": {"N": "N", "O": "E", "Z": "S", "W": "W"},
    # Some Spanish logs use L (leste) for east; some French and Spanish logs
    # already write W for west.
    "SPANISH": {"N": "N", "E": "E", "S": "S", "O": "W", "W": "W", "L": "E"},
    "FRENCH": {"N": "N", "E": "E", "S": "S", "O": "W", "W": "W"},
    "ENGLISH": {"N": "N", "E": "E", "S": "S", "W": "W"},
}

# Compass-point patterns per language; "by" is T in Dutch, B in English.
POINT = {
    "DUTCH": re.compile(r"^([NOZW]{1,3})(?:T([NOZW]{1,2}))?$"),
    "SPANISH": re.compile(r"^([NESOWL]{1,3})()$"),
    "FRENCH": re.compile(r"^([NESOW]{1,3})()$"),
    "ENGLISH": re.compile(r"^([NESW]{1,3})(?:B([NESW]{1,2}))?$"),
}

WORDS = {
    "DUTCH": {
        "TOT": "to", "EN": "and", "OF": "or", "VAR": "variable", "VARIABEL": "variable",
        "VEERLOOS": "variable", "STIL": "calm", "STILTE": "calm", "LOOPT": "veering",
        "RONDOM": "all round", "DOOR": "through", "NAAR": "to", "VAN": "from",
        "NOORD": "N", "NOORDE": "N", "OOST": "E", "ZUID": "S", "WEST": "W",
        "DOODSTIL": "dead calm",
    },
    "SPANISH": {
        "A": "to", "AL": "to", "Y": "and", "O": "or", "VAR": "variable", "VARIABLE": "variable",
        "VARIABLES": "variable", "CALMA": "calm", "CALMAS": "calm", "DEL": "from the",
        "DE": "from", "POR": "by", "VARIO": "variable", "VARIOS": "variable",
        "NORTE": "N", "SUR": "S", "ESTE": "E", "LESTE": "E", "OESTE": "W",
    },
    "FRENCH": {
        "DU": "from", "AU": "to", "ET": "and", "A": "to", "VAR": "variable",
        "VARIABLE": "variable", "VARIABLES": "variable", "CALME": "calm", "CALMES": "calm",
        "DE": "from", "LA": "the", "PARTIE": "quarter",
        "NORD": "N", "SUD": "S", "EST": "E", "OUEST": "W",
    },
    "ENGLISH": {},  # English words are kept as written, only re-cased
}

# Split into compass/word tokens, fractions/numbers, and separators.
TOKEN = re.compile(r"\d+\s*/\s*\d+|\d+(?:[.,]\d+)?|[A-Z]+|[^A-Z\d]+")
SEPARATOR = re.compile(r"^[\s\-,;/().:'\"+&!?]*$")


def _point(tok, lang):
    m = POINT[lang].match(tok)
    if not m:
        return None
    letters = LETTERS[lang]
    main, by = m.group(1), m.group(2)
    if len(main) == 3 and lang != "ENGLISH" and main[0] == main[1] == main[2]:
        return None  # "NNN" etc. is not a real point
    out = "".join(letters[c] for c in main)
    # A real point never contains opposite directions (rules out words like SOL).
    if ("E" in out and "W" in out) or ("N" in out and "S" in out):
        return None
    if by:
        out += "b" + "".join(letters[c] for c in by)
    return out


DUTCH_STYLE = re.compile(r"Z|[NOZW]T[NOZW]")


def convert(text, lang):
    """Convert one direction string; None means 'needs the model'."""
    if lang not in LETTERS:
        return None
    out = _convert(text, lang)
    # Some French and Spanish logbooks were written by Dutch officers (ZWTW, OTN).
    if out is None and lang in ("FRENCH", "SPANISH") and DUTCH_STYLE.search(text.upper()):
        out = _convert(text, "DUTCH")
    return out


def _convert(text, lang):
    s = text.strip().upper()
    if not s:
        return ""
    out = []
    for tok in TOKEN.findall(s):
        if tok[0].isdigit():
            out.append(re.sub(r"\s*/\s*", "/", tok))
        elif tok.isalpha():
            p = _point(tok, lang)
            if p is not None:
                out.append(p)
            elif lang == "ENGLISH":
                out.append(tok.lower())
            elif tok in WORDS[lang]:
                out.append(WORDS[lang][tok])
            else:
                return None
        elif SEPARATOR.match(tok):
            out.append(tok)
        else:
            return None
    result = "".join(out).strip()
    result = re.sub(r"\s+", " ", result)
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


if __name__ == "__main__":
    tests = [
        ("ZWTZ-ZZW-Z-ZTO", "DUTCH"), ("ZZO TOT OZO", "DUTCH"), ("VAR, ZZO", "DUTCH"),
        ("NO LIJK", "DUTCH"), ("SO A S", "SPANISH"), ("E Y E1/4 NE", "SPANISH"),
        ("SO1/4S - SO", "SPANISH"), ("DU S AU  S 1/4 SO", "FRENCH"),
        ("AU SO 1/4 O ET SO ET NNO", "FRENCH"), ("NBE", "ENGLISH"), ("CALM", "ENGLISH"),
    ]
    for t, l in tests:
        print(f"{l:8} {t!r:32} -> {convert(t, l)!r}")
