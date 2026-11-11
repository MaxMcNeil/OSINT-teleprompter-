"""Mode revue de presse : titres tapés (séparés par « | ») et/ou captures d'écran lues par Gemini."""
from __future__ import annotations

import os
import re

from google.genai import types

from . import llm

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_TITRES = 8


def _propre(t):
    t = " ".join(str(t).split()).strip(" -–—•·|\"'«»“”")
    return t[:220]


def titres_tapes(txt):
    return [x for x in (_propre(p) for p in re.split(r"\s*\|\s*|\n", txt or "")) if len(x.split()) >= 2]


def titres_captures(dossier):
    """Lit les titres d'actualité visibles sur les captures (une seule requête Gemini pour toutes les images)."""
    if not dossier or not os.path.isdir(dossier):
        return []
    imgs = []
    for nom in sorted(os.listdir(dossier)):
        ext = os.path.splitext(nom)[1].lower()
        path = os.path.join(dossier, nom)
        if ext in MIME and os.path.isfile(path) and 0 < os.path.getsize(path) <= 15_000_000:
            with open(path, "rb") as fh:
                imgs.append(types.Part.from_bytes(data=fh.read(), mime_type=MIME[ext]))
    if not imgs:
        print("   ! capture : aucune image .jpg/.png/.webp exploitable")
        return []
    print(f"   capture : {len(imgs)} image(s) envoyée(s) à Gemini pour lire les titres")
    p = ("Ces images sont des captures d'écran de sites ou d'applis d'actualité. Liste les TITRES D'ARTICLES visibles, "
         "mot pour mot dans leur langue d'origine, du plus en vue au moins en vue. Ignore les rubriques (« Artificial intelligence »), "
         "les heures (« 3 HOURS AGO »), les mentions « EXCLUSIVE », les menus, les cours de bourse, les publicités et les titres coupés "
         "illisibles (garde un titre coupé s'il reste compréhensible). Pour chaque titre, ajoute le sous-titre/chapô s'il est visible. "
         'Réponds en JSON : [{"titre": str, "chapo": str, "media": str}]')
    for essai in range(2):
        try:
            r = llm.ask(imgs + [p], temperature=0.0, json_mode=True, retries=4, fatal=False, gemini_d_abord=True)
            j = llm.parse_json(llm.text(r))
        except Exception as e:
            print(f"   ! lecture de la capture impossible ({str(e)[:90]})")
            if essai:
                return []
            continue
        if isinstance(j, dict):
            j = next((v for v in j.values() if isinstance(v, list)), [])
        out = []
        for x in j if isinstance(j, list) else []:
            if isinstance(x, dict) and isinstance(x.get("titre"), str) and len(x["titre"].split()) >= 2:
                t = _propre(x["titre"])
                if isinstance(x.get("chapo"), str) and x["chapo"].strip():
                    t += " — " + _propre(x["chapo"])
                if isinstance(x.get("media"), str) and x["media"].strip():
                    t += f" ({_propre(x['media'])})"
                out.append(t[:300])
        if out:
            return out
    return []


def assembler(titres_txt, dossier_capture):
    """Liste finale des titres (tapés d'abord, puis lus sur les captures), sans doublon, 8 au plus."""
    vus, out = set(), []
    for t in titres_tapes(titres_txt) + titres_captures(dossier_capture):
        k = re.sub(r"[^\w]+", " ", re.sub(r"\s*\([^()]*\)\s*$", "", t.split(" — ")[0]).lower()).strip()[:80]
        if k and k not in vus:
            vus.add(k)
            out.append(t)
    if len(out) > MAX_TITRES:
        print(f"   ! {len(out)} titres : on garde les {MAX_TITRES} premiers (les plus en vue)")
    return out[:MAX_TITRES]


def sujet_revue(titres, sujet=""):
    base = (sujet.strip() + " — ") if sujet.strip() else ""
    return base + "Revue de presse, relier ces affaires entre elles : " + " ; ".join(f"{i}) {t}" for i, t in enumerate(titres, 1))


def points_secours(titres):
    """Si l'analyse de la requête n'a pas donné un point par titre : un point par titre, recherches = le titre lui-même."""
    pts = []
    for i, t in enumerate(titres, 1):
        court = re.sub(r"\s*\(.*?\)\s*$", "", t.split(" — ")[0])
        pts.append({"id": f"P{i}", "intitule": t[:300], "requetes": [court[:90]]})
    return pts
