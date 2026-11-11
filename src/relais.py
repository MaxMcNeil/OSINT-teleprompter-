"""Relais IA gratuits (API compatibles OpenAI) : Groq -> Cerebras -> OpenRouter (modèles « :free »).

Chaque fournisseur est facultatif (sans clé, il est ignoré). Les modèles disponibles sont lus en direct chez chaque
fournisseur, puis classés selon nos préférences : un modèle retiré par le fournisseur ne casse jamais un run.
Quota du jour épuisé -> modèle écarté pour le run ; limite par minute -> courte pause puis modèle suivant ;
requête trop grosse pour un modèle -> on retient sa limite et on passe au suivant.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from collections import Counter

import requests

_TIMEOUT = float(os.getenv("LLM_CALL_TIMEOUT_S", "240"))
_lock = threading.Lock()


def _cles(*noms):
    out = []
    for n in noms:
        for v in os.environ.get(n, "").replace("\n", ",").split(","):
            v = v.strip()
            if v and v not in out:
                out.append(v)
    return out


FOURNISSEURS = [
    {"nom": "Groq", "url": "https://api.groq.com/openai/v1/chat/completions",
     "liste": "https://api.groq.com/openai/v1/models",
     "cles": ("GROQ_API_KEYS", "GROQ_API_KEY", "GROQ_API_KEYS_PLUS"),
     "pref": [r"kimi-k2", r"gpt-oss-120b", r"llama-3\.3-70b", r"qwen3-32b", r"llama-4-maverick", r"gpt-oss-20b", r"llama-4-scout"],
     "vision": [r"llama-4-scout", r"llama-4-maverick"],
     "defaut": ["moonshotai/kimi-k2-instruct-0905", "openai/gpt-oss-120b", "llama-3.3-70b-versatile",
                "meta-llama/llama-4-scout-17b-16e-instruct"]},
    {"nom": "Cerebras", "url": "https://api.cerebras.ai/v1/chat/completions",
     "liste": "https://api.cerebras.ai/v1/models",
     "cles": ("CEREBRAS_API_KEYS", "CEREBRAS_API_KEY"),
     "pref": [r"qwen-3-235b.*instruct", r"gpt-oss-120b", r"llama-3\.3-70b", r"qwen-3-32b", r"llama-4"],
     "vision": [],
     "defaut": ["gpt-oss-120b", "llama-3.3-70b"]},
    {"nom": "OpenRouter", "url": "https://openrouter.ai/api/v1/chat/completions",
     "liste": "https://openrouter.ai/api/v1/models",
     "cles": ("OPENROUTER_API_KEYS", "OPENROUTER_API_KEY"),
     "pref": [r"deepseek/deepseek-chat", r"kimi-k2", r"qwen3-235b", r"deepseek/deepseek-r1", r"gpt-oss-120b",
              r"llama-3\.3-70b", r"gemma-3-27b", r"mistral-small"],
     "vision": [r"llama-4", r"gemma-3-27b", r"qwen.*vl", r"mistral-small"],
     "defaut": ["deepseek/deepseek-chat-v3-0324:free", "meta-llama/llama-3.3-70b-instruct:free"],
     "gratuit_seulement": True},
]
_EXCLURE = re.compile(r"whisper|guard|tts|playai|embed|distil|compound|orpheus|safeguard|allam", re.I)

_modeles = {}            # fournisseur -> liste ordonnée (texte), et nom+"|vision" -> liste vision
_morts = set()           # (fournisseur, clé, modèle) : quota du jour épuisé / modèle retiré / clé refusée
_cles_ko = set()         # (fournisseur, clé)
_pause = {}              # (fournisseur, modèle) -> instant de fin de pause
_taille_max = {}         # (fournisseur, modèle) -> taille de prompt (caractères) refusée : on n'envoie plus au-dessus
USAGE = Counter()


def actifs():
    return [f for f in FOURNISSEURS if _cles(*f["cles"])]


def _classer(ids, prefs):
    out = []
    for p in prefs:
        for i in ids:
            if re.search(p, i, re.I) and i not in out and not _EXCLURE.search(i):
                out.append(i)
    return out


def modeles(f, vision=False):
    k = f["nom"] + ("|vision" if vision else "")
    if k in _modeles:
        return _modeles[k]
    ids = []
    try:
        h = {} if f.get("gratuit_seulement") else {"Authorization": f"Bearer {_cles(*f['cles'])[0]}"}
        r = requests.get(f["liste"], headers=h, timeout=30)
        data = r.json().get("data", []) if r.status_code == 200 else []
        for m in data:
            mid = m.get("id", "")
            if f.get("gratuit_seulement") and not mid.endswith(":free"):
                continue
            if vision and f.get("gratuit_seulement"):
                mods = ((m.get("architecture") or {}).get("input_modalities") or [])
                if "image" not in mods:
                    continue
            ids.append(mid)
    except Exception as e:
        print(f"  ! {f['nom']} : liste des modèles indisponible ({str(e)[:60]}), liste par défaut")
    prefs = f["vision"] if vision else f["pref"]
    choix = _classer(ids or f["defaut"], prefs) if prefs else []
    _modeles[k] = choix
    if choix:
        print(f"  relais {f['nom']}{' (images)' if vision else ''} : " + ", ".join(choix[:5]))
    return choix


def _messages(prompt, json_mode):
    sys_msg = ("Tu réponds UNIQUEMENT par du JSON valide, sans texte ni balise autour."
               if json_mode else "Tu réponds directement par le texte demandé, sans préambule ni commentaire.")
    if isinstance(prompt, str):
        return [{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}]
    parts = []
    for x in prompt:                                  # contenu multimodal façon Gemini (textes + types.Part image)
        if isinstance(x, str):
            parts.append({"type": "text", "text": x})
            continue
        inline = getattr(x, "inline_data", None)
        if inline is not None and getattr(inline, "data", None):
            b64 = base64.b64encode(inline.data).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:{inline.mime_type or 'image/jpeg'};base64,{b64}"}})
        elif getattr(x, "text", None):
            parts.append({"type": "text", "text": x.text})
    return [{"role": "system", "content": sys_msg}, {"role": "user", "content": parts}]


def _taille(prompt):
    if isinstance(prompt, str):
        return len(prompt)
    return sum(len(x) if isinstance(x, str) else 3000 for x in prompt)


class Reponse:
    def __init__(self, texte, source):
        self.text = texte
        self.source = source


def _nettoyer(t):
    t = re.sub(r"<think>.*?</think>", "", t or "", flags=re.S)
    return t.strip()


_REFUS = re.compile(
    r"^\W*(je (suis désolé|ne peux pas|ne suis pas en mesure|refuse)|désolé,? (mais )?je ne|i('m| am) sorry,? but|"
    r"i (can't|cannot|won't|am unable to)|i'm (not able|unable) to|as an ai|en tant qu'(ia|intelligence artificielle)|"
    r"mi dispiace,? ma|non posso|lo siento,? pero|no puedo|عذر[اً]|لا أستطيع|لا يمكنني|آسف)", re.I)


def refus(texte):
    """Réponse de refus/censure du modèle (et pas le texte demandé) : on passe au modèle suivant."""
    t = (texte or "").strip()
    return bool(t) and len(t) < 1200 and bool(_REFUS.search(t[:200]))


def ask(prompt, temperature=0.7, json_mode=False, deadline=None):
    """Essaie tous les relais gratuits. Retourne une Reponse, ou None si aucun n'a pu répondre."""
    vision = not isinstance(prompt, str)
    taille = _taille(prompt)
    msgs = _messages(prompt, json_mode)
    for f in actifs():
        cles = [c for c in _cles(*f["cles"]) if (f["nom"], c) not in _cles_ko]
        for m in modeles(f, vision):
            if taille >= _taille_max.get((f["nom"], m), 10 ** 9):
                continue
            if _pause.get((f["nom"], m), 0) > time.monotonic():
                continue
            r = None
            for c in cles:
                if (f["nom"], c, m) in _morts or (f["nom"], c) in _cles_ko:
                    continue
                for essai in range(3):
                    if deadline is not None and deadline():
                        return None
                    r = _appel(f, c, m, msgs, temperature, json_mode)
                    if isinstance(r, Reponse):
                        if refus(r.text):         # le modèle s'autocensure : un autre modèle écrit à sa place
                            print(f"  ! {f['nom']} {m} : refus du modèle (« {r.text[:60]}… ») : modèle suivant")
                            USAGE[f"refus {m.split('/')[-1]}"] += 1
                            r = "refus"
                            break
                        USAGE[f"{f['nom']} {m.split('/')[-1]}"] += 1
                        return r
                    if r == "attendre":
                        continue
                    break
                if r == "trop_gros":
                    with _lock:
                        _taille_max[(f["nom"], m)] = min(_taille_max.get((f["nom"], m), 10 ** 9), taille)
                if r in ("trop_gros", "pause", "modele_ko", "refus"):
                    break               # inutile d'essayer ce modèle avec une autre clé
    return None


def _appel(f, cle, m, msgs, temperature, json_mode):
    body = {"model": m, "messages": msgs, "temperature": max(0.0, min(1.0, temperature)), "max_tokens": 8000}
    if "gpt-oss" in m:
        body["reasoning_effort"] = "low"
    h = {"Authorization": f"Bearer {cle}", "Content-Type": "application/json"}
    if f["nom"] == "OpenRouter":
        h.update({"HTTP-Referer": "https://github.com/MaxMcNeil/OSINT-teleprompter-", "X-Title": "OSINT-teleprompter"})
    try:
        r = requests.post(f["url"], json=body, headers=h, timeout=_TIMEOUT)
    except Exception as e:
        print(f"  ! {f['nom']} {m} : pas de réponse ({type(e).__name__}) : modèle suivant")
        _pause[(f["nom"], m)] = time.monotonic() + 90
        return "pause"
    txt = r.text[:400]
    low = txt.lower()
    if r.status_code == 200:
        try:
            j = r.json()
            out = _nettoyer(j["choices"][0]["message"].get("content") or "")
        except Exception:
            out = ""
        if out:
            return Reponse(out, f"{f['nom']} {m}")
        print(f"  ! {f['nom']} {m} : réponse vide : modèle suivant")
        return "pause"
    if r.status_code in (401, 403) and "model" not in low:
        print(f"  ! {f['nom']} : clé refusée ({r.status_code}) : écartée pour ce run")
        _cles_ko.add((f["nom"], cle))
        return "cle_ko"
    if r.status_code == 413 or any(x in low for x in ("too large", "context length", "context_length", "reduce the length",
                                                       "maximum context", "request too big", "tokens per minute (tpm): limit")):
        print(f"  ! {f['nom']} {m} : requête trop grosse pour ce modèle : modèle suivant")
        return "trop_gros"
    if r.status_code == 404 or "model_not_found" in low or "decommissioned" in low or "does not exist" in low:
        print(f"  ! {f['nom']} {m} : modèle indisponible : écarté")
        for k in _cles(*f["cles"]):
            _morts.add((f["nom"], k, m))
        return "modele_ko"
    if r.status_code == 429:
        if any(x in low for x in ("per day", "(tpd)", "(rpd)", "daily", "free-models-per-day")):
            print(f"  ! {f['nom']} {m} : quota du jour épuisé : écarté pour ce run")
            _morts.add((f["nom"], cle, m))
            return "jour"
        try:
            wait = float(r.headers.get("retry-after", "") or 0)
        except ValueError:
            wait = 0
        m2 = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", low)
        if m2:
            wait = max(wait, int(m2.group(1) or 0) * 60 + float(m2.group(2)))
        wait = wait or 10
        if wait <= 30:
            time.sleep(wait + 0.5)
            return "attendre"
        _pause[(f["nom"], m)] = time.monotonic() + wait
        print(f"  ! {f['nom']} {m} : limite par minute ({wait:.0f}s) : modèle suivant")
        return "pause"
    print(f"  ! {f['nom']} {m} : erreur {r.status_code} ({' '.join(txt.split())[:120]}) : modèle suivant")
    _pause[(f["nom"], m)] = time.monotonic() + 90
    return "pause"


def resume():
    return ", ".join(f"{k} ×{v}" for k, v in USAGE.most_common())
