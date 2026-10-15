"""Enveloppe Gemini : retries, JSON, recherche Google intégrée."""
import json
import os
import re
import threading
import time

from google import genai
from google.genai import types

# Aucun filtre côté API : le ton est piloté par les prompts.
SAFETY = [
    types.SafetySetting(category=c, threshold="BLOCK_NONE")
    for c in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]

# Palier gratuit : ~5 requêtes/minute PAR CLÉ ET PAR MODÈLE. Compte payant : monte LLM_RPM (ex. 60).
RPM = float(os.getenv("LLM_RPM", "4"))
SOFT_BLOCK = 90      # secondes d'exclusion d'un couple clé/modèle après une erreur 503
_lock = threading.Lock()
_next = {}           # clé -> instant avant lequel on n'envoie rien (cadence + pauses 429)
_dead = set()        # (clé, modèle, recherche?) : quota journalier épuisé ou modèle introuvable
_soft = {}           # (clé, modèle) -> instant de fin d'exclusion temporaire
_clients = {}
_announced = set()
_KEYS = None
MODELS = None
_BAD = ("image", "tts", "live", "audio", "embedding", "robotics", "computer", "veo", "imagen",
        "learnlm", "gemma", "thinking", "omni", "native", "-latest")


def keys():
    """GEMINI_API_KEY, GEMINI_API_KEY_2 … GEMINI_API_KEY_9 (et/ou GEMINI_API_KEYS séparées par des virgules)."""
    global _KEYS
    if _KEYS is None:
        found = []
        names = ["GEMINI_API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
        vals = [os.environ.get(n, "") for n in names] + os.environ.get("GEMINI_API_KEYS", "").split(",")
        for v in vals:
            v = v.strip()
            if v and v not in found:
                found.append(v)
        if not found:
            raise SystemExit("Aucune clé Gemini : ajoute le secret GEMINI_API_KEY (et GEMINI_API_KEY_2…5 si tu en as).")
        _KEYS = found
        for i in range(len(found)):
            _next[i] = 0.0
        print(f"  {len(found)} clé(s) Gemini chargée(s)")
    return _KEYS


def client(i=0):
    if i not in _clients:
        _clients[i] = genai.Client(api_key=keys()[i])
    return _clients[i]


def _rank(name: str):
    """Du plus performant au moins performant : version récente d'abord, flash avant flash-lite, stable avant preview."""
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    version = float(m.group(1)) if m else 0.0
    return (-version, "lite" in name, "preview" in name or "exp" in name, name)


def models():
    global MODELS
    if MODELS is not None:
        return MODELS
    forced = os.getenv("GEMINI_MODEL", "").strip()
    found = []
    try:
        for m in client(0).models.list():
            name = (m.name or "").replace("models/", "")
            acts = getattr(m, "supported_actions", None) or []
            if "flash" in name and "generateContent" in acts and not any(b in name for b in _BAD):
                found.append(name)
        found.sort(key=_rank)
    except Exception as e:
        print(f"  ! liste des modèles indisponible ({str(e)[:80]}), repli sur la liste par défaut")
    if not found:
        found = ["gemini-3-flash-preview", "gemini-2.5-flash"]
    MODELS = ([forced] if forced else []) + [m for m in found if m != forced]
    print("  modèles, du plus performant au moins performant :", ", ".join(MODELS))
    return MODELS


_strikes = {}


def _pick(search: bool):
    """Choisit (clé, modèle) et réserve son créneau. Retourne (clé, modèle, attente) ; (None, None, attente) si tout est
    temporairement bloqué ; (None, None, None) si tout est épuisé pour la journée."""
    ms = models()
    n = len(keys())
    with _lock:
        now = time.monotonic()
        options, any_live, soft_wait = [], False, None
        for rank, m in enumerate(ms):
            live = [i for i in range(n)
                    if (i, m, False) not in _dead and not (search and (i, m, True) in _dead)]
            if live:
                any_live = True
            ready = [i for i in live if _soft.get((i, m), 0) <= now]
            if ready:
                i = min(ready, key=lambda k: _next[k])
                options.append((rank, i, m, max(0.0, _next[i] - now)))
            else:
                for i in live:
                    w = _soft[(i, m)] - now
                    soft_wait = w if soft_wait is None else min(soft_wait, w)
        if not any_live:
            return None, None, None
        if not options:
            return None, None, max(1.0, soft_wait or 5.0)
        # Meilleur modèle dont l'attente est raisonnable ; sinon le créneau le plus proche.
        good = [o for o in options if o[3] <= 8]
        rank, i, m, wait = min(good, key=lambda o: o[0]) if good else min(options, key=lambda o: o[3])
        _next[i] = max(now, _next[i]) + 60.0 / RPM
        return i, m, wait


def _cooldown(i: int, seconds: float):
    """Google dit "réessaie dans N s" : cette clé attend, les autres continuent."""
    with _lock:
        _next[i] = max(_next[i], time.monotonic() + seconds)


def _quota_info(msg: str) -> str:
    m = re.search(r"Quota exceeded for metric: ([^,]+), limit: (\d+)", msg)
    return f"{m.group(1).split('/')[-1]} (limite {m.group(2)})" if m else msg[:160]


def ask(prompt: str, temperature: float = 0.7, json_mode: bool = False,
        search: bool = False, retries: int = 8, fatal: bool = True):
    """fatal=False : une panne de quota lève RuntimeError (récupérable) au lieu d'arrêter tout le run."""
    cfg = {"safety_settings": SAFETY, "temperature": temperature}
    if json_mode:
        cfg["response_mime_type"] = "application/json"
    if search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    last, attempt, guard = None, 0, 0
    while attempt < retries and guard < 400:
        guard += 1
        i, model, wait = _pick(search)
        if i is None and wait is None:
            msg = ("Quota JOURNALIER épuisé sur tous les modèles et toutes les clés (" + ", ".join(models())
                   + "). Réessaie après 9h (Paris), ou active la facturation sur une clé.")
            if fatal:
                raise SystemExit(msg)
            raise RuntimeError(msg)
        if i is None:
            time.sleep(min(wait, 30))
            continue
        if wait:
            time.sleep(wait)
        if (i, model) not in _announced:
            _announced.add((i, model))
            print(f"  > clé n°{i + 1} / {model}")
        try:
            r = client(i).models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(**cfg),
            )
            _strikes.pop((i, model, bool(search)), None)
            return r
        except Exception as e:  # réseau, quota, surcharge
            last = e
            msg = str(e)
            head = msg[:80]
            if ("API key" in msg and ("not valid" in msg or "expired" in msg)) or "PERMISSION_DENIED" in head \
                    or head.startswith("403") or "API_KEY_INVALID" in msg:
                print(f"  ! clé n°{i + 1} refusée par Google ({head[:50]}) : écartée pour ce run")
                for m_ in models():
                    _dead.add((i, m_, False))
                continue
            if "INVALID_ARGUMENT" in head or head.startswith("400"):
                raise RuntimeError(f"requête refusée par Gemini : {msg[:200]}")
            if "NOT_FOUND" in msg or "404" in msg[:40]:
                print(f"  ! {model} introuvable (clé n°{i + 1}), suivant")
                _dead.add((i, model, False))
                continue
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                if "PerDay" in msg or "per day" in msg.lower():
                    print(f"  ! quota journalier épuisé : clé n°{i + 1} / {model}"
                          + (" (recherche Google)" if search else ""))
                    _dead.add((i, model, bool(search)))
                    continue
                m = re.search(r"retry(?:Delay)?\D{0,20}(\d+(?:\.\d+)?)\s*s", msg, re.I)
                k = (i, model, bool(search))
                _strikes[k] = _strikes.get(k, 0) + 1
                if _strikes[k] == 1:
                    print(f"    (429 brut : {' '.join(msg.split())[:300]})")
                if _strikes[k] >= (2 if not m else 4):
                    print(f"  ! quota inutilisable : clé n°{i + 1} / {model}"
                          + (" (recherche Google)" if search else "") + " : écarté pour ce run")
                    _dead.add((i, model, bool(search)))
                    continue
                pause = float(m.group(1)) + 2 if m else 20
                print(f"  ! quota par minute : clé n°{i + 1} / {model}, pause {pause:.0f}s sur ce modèle seulement")
                with _lock:
                    _soft[(i, model)] = time.monotonic() + pause
                continue
            elif "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
                print(f"  ! {model} surchargé (clé n°{i + 1}) : on passe au modèle suivant pendant {SOFT_BLOCK}s")
                with _lock:  # la surcharge concerne le modèle : on le met en pause pour toutes les clés
                    for k in range(len(keys())):
                        _soft[(k, model)] = time.monotonic() + SOFT_BLOCK
                continue
            else:
                pause = 3 * 2 ** attempt
                print(f"  ! LLM: {msg[:120]} -> nouvel essai dans {pause}s")
                time.sleep(pause)
                attempt += 1
    raise RuntimeError(f"LLM indisponible: {str(last)[:200]}")


def text(resp) -> str:
    try:
        return (resp.text or "").strip()
    except Exception:
        return ""


def parse_json(s: str):
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip())
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"(\{.*\}|\[.*\])", s, re.S)
        if not m:
            raise
        return json.loads(m.group(1))


def ask_json(prompt: str, temperature: float = 0.3):
    for _ in range(2):
        try:
            return parse_json(text(ask(prompt, temperature=temperature, json_mode=True)))
        except Exception as e:
            print(f"  ! JSON invalide ({str(e)[:80]}), nouvel essai")
    return None
