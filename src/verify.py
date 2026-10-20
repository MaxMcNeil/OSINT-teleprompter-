"""Vérification croisée automatique : pour chaque fait fragile (source faible, allégation, signal, opinion), le workflow
cherche lui-même une source plus solide qui le CONFIRME (ou le contredit). Aucun fait n'est supprimé : il est marqué."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import collect, llm
from .facts import nums

RANK = {"haute": 3, "moyenne": 2, "faible": 1}


def _fold(t):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (t or "").lower())).strip()


def is_weak(f):
    return f.get("fiabilite") == "faible" or f.get("statut") in ("allegation", "signal", "opinion")


def query_for(f):
    toks = re.findall(r"[A-ZÉÈÀÂÎÔÇ][\wéèêàâîôçù'’-]+|\d[\d.,]*", f["fact"])
    toks = [t for t in dict.fromkeys(toks) if t.lower() not in ("selon", "le", "la", "les", "un", "une", "il", "elle")]
    q = " ".join(toks[:8]) or " ".join(f["fact"].split()[:8])
    return q


def _search(f, lang, n=6):
    q = query_for(f)
    out = []
    out += collect.google_news(q, lang["hl"], lang["gl"], n)
    out += collect.bing_news(q, f"{lang['hl']}-{lang['gl']}", n)
    return out


def _judge(f, cands):
    blocks = "\n\n".join(f"[{s.id}] ({s.publisher}, fiabilité {s.meta.get('fiab')}, {s.date}) {s.title}\n{s.text[:2500]}" for s in cands)
    p = f"""FAIT À VÉRIFIER : {f['fact']}
(Il vient d'une source jugée fragile. Cherche dans les SOURCES ci-dessous une source INDÉPENDANTE qui l'établit ou le contredit.)

Réponds en JSON : {{"verdict": "confirme|contredit|rien", "source_id": "S12", "citation": "extrait EXACT copié de la source (20 à 200 caractères)"}}
Règles : "confirme" seulement si la source dit bien la même chose (mêmes personnes, mêmes chiffres, mêmes dates). Sinon "rien".

SOURCES :
{blocks}"""
    j = llm.ask_json(p, temperature=0.0)
    return j if isinstance(j, dict) else {}


def corroborate(facts, sources, lang, enrich, assign_ids, nxt, max_facts=14):
    """Modifie `facts` en place, ajoute les nouvelles sources à `sources`. Retourne (stats, nxt)."""
    weak = sorted((f for f in facts if is_weak(f)), key=lambda f: -(f["importance"] * 2 + f["choc"]))[:max_facts]
    stats = {"verifies": 0, "confirmes": 0, "contredits": 0, "non_corrobores": 0, "indisponibles": 0}
    if not weak:
        return stats, nxt
    by_id = {s.id: s for s in sources}
    pool = []

    def search(f):
        try:
            return collect.dedupe(_search(f, lang), known={s.url for s in sources})
        except Exception:
            return []

    with ThreadPoolExecutor(4) as ex:
        found = list(ex.map(search, weak))
    seen, per_fact = set(), []
    for f, lst in zip(weak, found):
        keep = []
        for s in lst:
            if s.url in seen or s.url == by_id.get(f["source_id"], collect.Source()).url:
                continue
            seen.add(s.url)
            keep.append(s)
            if len(keep) >= 5:
                break
        per_fact.append(keep)
        pool += keep
    nxt = assign_ids(pool, nxt)
    try:
        enrich(pool, lang)
    except Exception as e:
        print(f"   ! textes de vérification partiels ({str(e)[:70]})")
    for s in pool:
        s.meta.setdefault("fiab", collect.reliability(s))
        s.meta["via_verif"] = True
        if not s.text:
            s.text = s.title
    sources.extend(pool)
    by_id.update({s.id: s for s in pool})

    def judge(item):
        f, cands = item
        if not cands:
            return "non_corrobore", None, None
        try:
            j = _judge(f, cands)
        except (Exception, SystemExit):
            return "indisponible", None, None
        sid = j.get("source_id") if isinstance(j.get("source_id"), str) else ""
        s = by_id.get(sid)
        cit = _fold(j.get("citation") if isinstance(j.get("citation"), str) else "")
        ok_src = s is not None and s in cands and len(cit) >= 20 and cit in _fold(s.text)   # citation réellement présente
        if j.get("verdict") == "confirme" and ok_src and nums(f["fact"]) <= nums(s.text + " " + s.title):
            return "confirme", s, cit
        if j.get("verdict") == "contredit" and ok_src:
            return "contredit", s, cit
        return "non_corrobore", None, None

    with ThreadPoolExecutor(3) as ex:
        verdicts = list(ex.map(judge, zip(weak, per_fact)))
    for f, (v, s, cit) in zip(weak, verdicts):
        stats["verifies"] += 1
        if v == "confirme":
            stats["confirmes"] += 1
            f["verification"] = "confirme"
            f["corrobore_par"] = s.id
            if RANK.get(s.meta.get("fiab"), 1) > RANK.get(f.get("fiabilite"), 1):
                f["source_initiale"] = f["source_id"]          # la citation pointe désormais vers la source la plus solide
                f["source_id"], f["fiabilite"] = s.id, s.meta["fiab"]
        elif v == "contredit":
            stats["contredits"] += 1
            f["verification"] = "contredit"
            f["contredit_par"] = s.id
        elif v == "indisponible":
            stats["indisponibles"] += 1
            f["verification"] = "indisponible"
        else:
            stats["non_corrobores"] += 1
            f["verification"] = "non_corrobore"
    return stats, nxt
