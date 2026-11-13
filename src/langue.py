"""Contrôle de la langue du script : un live = une seule langue, sans exception.

Chaque paragraphe est identifié (écriture arabe / autres alphabets / langues latines par mots-outils).
Un paragraphe dans une autre langue que celle du live est d'abord réécrit, puis traduit, puis retiré en dernier recours
(et signalé dans STATUT.txt) : jamais un script en deux langues sans que tu le saches.
"""
from __future__ import annotations

import re

MOTS = {
    "fr": {"le", "la", "les", "des", "du", "de", "un", "une", "et", "pour", "sur", "avec", "est", "sont", "qui", "que",
           "dans", "pas", "ce", "cette", "il", "elle", "nous", "vous", "au", "aux", "mais", "ou", "leur", "plus"},
    "en": {"the", "of", "and", "for", "with", "is", "are", "to", "in", "on", "that", "this", "it", "was", "were", "be",
           "by", "from", "has", "have", "not", "but", "they", "their", "which", "will", "would"},
    "it": {"il", "gli", "della", "delle", "dei", "del", "nel", "sul", "alla", "per", "con", "una", "che", "non", "sono",
           "questo", "anche", "più", "lo", "è", "di", "da", "nella", "ha", "come", "ma"},
    "es": {"el", "los", "las", "del", "por", "para", "con", "una", "que", "es", "en", "y", "se", "su", "lo", "como",
           "más", "pero", "sus", "al", "este", "esta"},
    "de": {"der", "die", "das", "und", "mit", "für", "von", "ist", "nicht", "ein", "eine", "auf", "den", "dem", "sich",
           "auch", "es", "zu", "im", "wird"},
    "pt": {"os", "as", "da", "do", "para", "com", "uma", "que", "não", "em", "por", "mais", "como", "dos", "das",
           "ao", "foi", "são", "seu", "sua"},
}
NOMS = {"fr": "français", "en": "anglais", "it": "italien", "es": "espagnol", "de": "allemand", "pt": "portugais",
        "ar": "arabe"}


def _ecritures(p):
    lettres = [c for c in p if c.isalpha()]
    n = len(lettres) or 1
    arabe = sum("؀" <= c <= "ۿ" or "ݐ" <= c <= "ݿ" or "ﭐ" <= c <= "﻿" for c in lettres)
    latin = sum(c.isascii() or "À" <= c <= "ɏ" for c in lettres)
    return arabe / n, latin / n, (n - arabe - latin) / n


def langue_paragraphe(p):
    """Code de langue du paragraphe ('ar', 'fr', 'en'…), 'autre' (autre alphabet) ou None (trop court / indécidable)."""
    ar, lat, autre = _ecritures(p)
    if ar >= 0.5:
        return "ar"
    if autre >= 0.5:
        return "autre"
    mots = re.findall(r"[a-zà-ÿ']+", p.lower().replace("’", "'"))
    if len(mots) < 8:
        return None
    w = set(m.split("'")[-1] for m in mots)
    score = {k: len(w & v) for k, v in MOTS.items()}
    best = max(score, key=score.get)
    return best if score[best] >= 3 else None


def paragraphe_ok(p, code):
    if len(p.split()) < 6:              # titres, chutes courtes : on ne juge pas
        return True
    ar, lat, autre = _ecritures(p)
    if code == "ar":
        return ar >= 0.6 and autre < 0.2        # noms propres en latin tolérés
    if ar > 0.03 or autre > 0.05:              # écriture arabe ou autre glissée dans un live en langue latine
        return False
    lp = langue_paragraphe(p)
    if lp is None or lp == code:
        return True
    mots = set(re.findall(r"[a-zà-ÿ']+", p.lower()))
    return len(mots & MOTS.get(lp, set())) < 2 * max(1, len(mots & MOTS.get(code, set())))


def paragraphes(texte):
    return [x for x in re.split(r"\n\s*\n", texte or "") if x.strip()]


def mauvais(texte, code):
    """Indices des paragraphes qui ne sont pas dans la langue du live."""
    return [i for i, p in enumerate(paragraphes(texte)) if not paragraphe_ok(p, code)]


def corriger(texte, code, nom, traduire):
    """Traduit les paragraphes fautifs (traduire(paragraphe) -> texte) ; retire ceux qui restent fautifs.
    Retourne (texte, n_traduits, n_retires)."""
    paras = paragraphes(texte)
    tr, rm, out = 0, 0, []
    for p in paras:
        if paragraphe_ok(p, code):
            out.append(p)
            continue
        q = None
        try:
            q = traduire(p)
        except Exception as e:
            print(f"   ! traduction impossible ({str(e)[:60]})")
        if q and paragraphe_ok(q, code) and len(re.findall(r"\[F\d+\]", q)) >= len(re.findall(r"\[F\d+\]", p)) - 1:
            out.append(q)
            tr += 1
        else:
            rm += 1
    return "\n\n".join(out), tr, rm
