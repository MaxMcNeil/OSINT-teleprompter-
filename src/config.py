"""Configuration centrale."""
import os

UA = "Mozilla/5.0 (compatible; OSINTLiveScript/1.0; +https://github.com)"

# Débit oral moyen (mots / minute). 145 = rythme "live nerveux" mais intelligible.
WPM = int(os.getenv("WPM", "145"))

# Un fait "consomme" environ ce nombre de mots une fois habillé (contexte, punch, transition).
WORDS_PER_FACT = 38

# Nombre de requêtes de recherche générées / recherches Google (Gemini) lancées.
# Chaque recherche Google = 1 appel LLM : on reste raisonnable pour le palier gratuit.
N_QUERIES = int(os.getenv("N_QUERIES", "6"))
GROUNDED_MAX = int(os.getenv("GROUNDED_MAX", "4"))

# Éditions Google News balayées (presse internationale)
EDITIONS = [("fr", "FR"), ("en", "US"), ("en", "GB"), ("es", "ES"), ("de", "DE")]

# Top presse internationale / agences, balayée via "site:"
TOP_PRESS = [
    "reuters.com", "apnews.com", "afp.com", "bbc.com", "theguardian.com",
    "nytimes.com", "washingtonpost.com", "ft.com", "bloomberg.com", "politico.eu",
    "aljazeera.com", "dw.com", "spiegel.de", "elpais.com", "cnn.com",
    "lemonde.fr", "lefigaro.fr", "liberation.fr", "mediapart.fr", "franceinfo.fr",
    "france24.com", "lesechos.fr", "lexpress.fr", "lepoint.fr",
]

OFFICIAL_SUFFIX = (
    ".gouv.fr", "europa.eu", "assemblee-nationale.fr", "senat.fr", "courdescomptes.fr",
    "insee.fr", "conseil-constitutionnel.fr", "hatvp.fr", "elysee.fr", ".gov",
    "un.org", "worldbank.org", "imf.org", "oecd.org",
)

LANGS = {
    "fr": ("fr", "FR", "français"),
    "en": ("en", "US", "English"),
    "es": ("es", "ES", "español"),
    "de": ("de", "DE", "Deutsch"),
    "it": ("it", "IT", "italiano"),
    "pt": ("pt", "BR", "português"),
    "ar": ("ar", "AE", "العربية"),
}


def _detect(sujet: str) -> str:
    if any("\u0600" <= c <= "\u06FF" for c in sujet):
        return "ar"
    w = set(sujet.lower().replace("'", " ").split())
    marks = {
        "fr": {"le", "la", "les", "des", "du", "de", "un", "une", "et", "pour", "sur", "avec", "pourquoi", "en", "au", "aux"},
        "en": {"the", "of", "and", "for", "with", "why", "to", "in", "on", "is", "are", "how", "what", "who", "against"},
        "es": {"el", "los", "las", "del", "por", "para", "con", "una", "y"},
        "de": {"der", "die", "das", "und", "mit", "für", "von", "ist"},
        "it": {"il", "gli", "della", "delle", "dei", "del", "nel", "sul", "alla", "per", "con", "una", "e", "è", "che", "non",
               "sono", "perché", "questo", "governo", "anche", "più", "lo"},
        "pt": {"os", "as", "da", "do", "para", "com", "uma", "e"},
    }
    best = max(marks, key=lambda k: len(w & marks[k]))
    return best if w & marks[best] else "fr"


def lang_cfg(code: str, sujet: str) -> dict:
    code = (code or "auto").lower()
    if code == "auto":
        code = _detect(sujet)
    hl, gl, nom = LANGS.get(code, LANGS["fr"])
    return {"code": code if code in LANGS else "fr", "hl": hl, "gl": gl, "nom": nom}
