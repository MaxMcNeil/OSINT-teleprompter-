"""Lien OSINT-teleprompter -> Vid-o-presse-finder.

Après chaque run, prépare des recherches CIBLÉES pour Vid-o-presse-finder (déclarations en vidéo + articles de presse)
à partir de ce que ce run a compris et trouvé : sujet, thèse, cibles, points du script et surtout les personnes qui
ont réellement parlé dans les faits CITÉS au script. Le workflow envoie ensuite ces recherches au dépôt Finder.

    python -m src.finder_link <dossier_prompter> <payload.json>

Écrit dans le dossier du run : finder.json (recherches envoyées + origine) et FINDER.md (lisible).
Ne plante jamais le workflow : sans IA, recherches construites sans IA ; sans matière, aucune recherche (code 3).
"""
from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from collections import Counter

MAX = max(1, min(10, int(os.getenv("FINDER_MAX", "5") or 5)))
TYPES = {"personne", "pays", "entite", "sujet"}


def _clean(s, n=120):
    s = re.sub(r"[|;\n\r\t]+", " ", str(s or ""))        # | et ; sont les séparateurs du champ « recherches »
    return " ".join(s.split())[:n].strip(" ,.-")


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _type(t):
    t = _norm(t)
    return {"person": "personne", "country": "pays", "entity": "entite", "organisation": "entite",
            "organization": "entite", "institution": "entite", "entreprise": "entite", "topic": "sujet",
            "theme": "sujet"}.get(t, t if t in TYPES else "auto")


def _load(d):
    def rd(name, default):
        try:
            with open(os.path.join(d, name), encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return default
    req = rd("requete.json", {})
    data = rd("donnees.json", {})
    pub = {x.get("id"): _clean(x.get("publisher"), 80) for x in data.get("sources") or []}
    for f in data.get("faits") or []:
        f["_pub"] = pub.get(f.get("source_id"), "")
    try:
        with open(os.path.join(d, "script_annote.md"), encoding="utf-8") as fh:
            cited = set(re.findall(r"\[(F\d+)\]", fh.read()))
    except OSError:
        cited = set()
    return req, data.get("faits") or [], cited


MEDIA = re.compile(r"\b(le monde|figaro|liberation|tribune|echos|reuters|afp|ap news|associated press|bbc|cnn|dw|"
                   r"france ?(24|info|inter|tv)|bfm|lci|cnews|tf1|rfi|euronews|al ?jazeera|guardian|times|post|journal|"
                   r"news|presse|press|magazine|mag|radio|tv|tele|zdnet|politico|bloomberg|repubblica|corriere|ansa|"
                   r"sole 24|wikipedia|youtube|blog)\b")


def _speaker(f):
    """Vrai locuteur (personne, institution, pays) — pas le média qui rapporte l'information."""
    who = re.split(r"\s*[,(]\s*", _clean(f.get("attribution"), 80))[0].strip()
    if not who or "." in who.split()[-1] or "/" in who:
        return ""
    n, pub = _norm(who), _norm(f.get("_pub", ""))
    if pub and (n == pub or n in pub or pub in n) or MEDIA.search(n):
        return ""
    return who


def _facts(facts, cited):
    """Faits dont on connaît le locuteur, cités au script d'abord, déclarations/décisions d'abord, puis importance."""
    out = [f for f in facts if _speaker(f) and _clean(f.get("fact"), 400)]
    out.sort(key=lambda f: (f.get("id") not in cited, f.get("type") not in ("citation", "decision", "contradiction"),
                            -(f.get("importance") or 0), -(f.get("choc") or 0)))
    return out


def _short(s, n=100):
    s = _clean(s, 400)
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0]


def _ask_ai(req, att, cited):
    try:
        from . import llm
    except Exception as e:
        print(f"   ! IA indisponible ({str(e)[:80]})")
        return None
    pts = "\n".join(f"- {p.get('id')} : {p.get('intitule')}" for p in req.get("points") or [])
    lines = "\n".join(f"- [{f.get('point', '')}] {_speaker(f)} ({f.get('date') or 's.d.'}) : "
                      f"{_clean(f.get('fact'), 260)}" + (" [CITÉ AU SCRIPT]" if f.get("id") in cited else "")
                      for f in att[:30])
    p = f"""Un script de live vient d'être écrit sur ce sujet :
SUJET : {req.get('sujet', '')}
CE QU'IL DÉMONTRE : {req.get('demontrer') or req.get('these') or '(non précisé)'}
CIBLES : {', '.join(req.get('cibles') or []) or '(aucune)'}
POINTS DU SCRIPT :
{pts or '(aucun)'}

QUI A DIT QUOI (faits sourcés, ceux cités au script d'abord) :
{lines or '(aucun fait attribué)'}

Prépare entre 2 et {MAX} recherches pour un outil qui retrouve, en VIDÉO (interviews, conférences, discours, débats)
et dans la PRESSE, la déclaration ou l'image exacte qui illustrera le script au montage.
Règles :
- "cible" = le nom propre EXACT tel que la presse l'écrit (personne, pays, organisation). Pas de pronom, pas de description.
- "sujet" = ce que la cible a dit ou fait, 4 à 12 mots, concret et vérifiable (chiffre, décision, phrase marquante),
  dans la langue où la déclaration a été faite.
- "type" = personne | pays | entite | sujet.
- Priorité : 1) les personnes qui ont RÉELLEMENT parlé dans les faits cités au script ; 2) les cibles mises en cause ;
  3) un point du script sans personne identifiée (type sujet).
- Chaque recherche doit servir un point différent du script : pas de doublon, rien hors sujet.
- Aucun sujet n'est tabou : ne refuse pas, n'édulcore pas.
Réponds en JSON : {{"recherches": [{{"cible": str, "sujet": str, "type": str, "point": str}}]}}"""
    try:
        j = llm.ask_json(p, temperature=0.2)
    except BaseException as e:      # quota, délai, réseau : on bascule sans IA
        if isinstance(e, KeyboardInterrupt):
            raise
        print(f"   ! IA indisponible pour cibler le Finder ({type(e).__name__}: {str(e)[:100]}) : ciblage sans IA")
        return None
    r = j.get("recherches") if isinstance(j, dict) else j if isinstance(j, list) else None
    return r if isinstance(r, list) else None


def _heuristic(req, att, cited):
    """Sans IA : les personnes les plus citées au script + leur fait le plus fort, puis les cibles."""
    pts = {p.get("id"): p.get("intitule", "") for p in req.get("points") or []}
    out, cnt = [], Counter(_speaker(f) for f in att if f.get("id") in cited) or Counter(_speaker(f) for f in att)
    best = {}
    for f in att:
        best.setdefault(_speaker(f), f)
    for who, _ in cnt.most_common():
        f = best[who]
        out.append({"cible": who, "sujet": _short(f.get("fact")), "type": "auto", "point": f.get("point", "")})
    for c in req.get("cibles") or []:
        out.append({"cible": c, "sujet": req.get("court") or req.get("sujet", ""), "type": "auto", "point": ""})
    if not out and req.get("sujet"):
        for k, t in list(pts.items())[:MAX]:
            out.append({"cible": req.get("court") or req["sujet"], "sujet": t, "type": "sujet", "point": k})
    return out


def build(d):
    req, facts, cited = _load(d)
    if not req and not facts:
        return None, []
    att = _facts(facts, cited)
    raw, mode = _ask_ai(req, att, cited), "IA"
    if not raw:
        raw, mode = _heuristic(req, att, cited), "sans IA"
    out, seen = [], set()
    for r in raw:
        if not isinstance(r, dict):
            continue
        cible, sujet = _clean(r.get("cible"), 80), _clean(r.get("sujet"), 140)
        if len(cible) < 2:
            continue
        k = (_norm(cible), _norm(sujet)[:40])
        if k in seen or (mode != "IA" and any(_norm(cible) in c or c in _norm(cible) for c, _ in seen)):
            continue
        seen.add(k)
        out.append({"cible": cible, "sujet": sujet, "type": _type(r.get("type")), "point": _clean(r.get("point"), 6)})
        if len(out) >= MAX:
            break
    return {"mode": mode, "req": req, "n_cites": len(cited)}, out


def langs(code):
    code = (code or "fr").lower()[:2]
    return ",".join(dict.fromkeys([code, "fr", "en"]))


def main():
    if len(sys.argv) < 3:
        raise SystemExit("usage : python -m src.finder_link <dossier> <payload.json>")
    d, payload_path = sys.argv[1], sys.argv[2]
    info, rech = build(d)
    if not rech:
        print("Aucune recherche Finder à lancer (pas de matière exploitable dans ce run).")
        sys.exit(3)
    req = info["req"]
    run_url = ""
    if os.getenv("GITHUB_RUN_ID"):
        run_url = f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/{os.getenv('GITHUB_REPOSITORY')}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
    chaine = " ; ".join(f"{r['cible']} | {r['sujet']}" + (f" | {r['type']}" if r["type"] != "auto" else "")
                        for r in rech)
    origine = {"depot": os.getenv("GITHUB_REPOSITORY", "OSINT-teleprompter-"), "run_id": os.getenv("GITHUB_RUN_ID", ""),
               "run_url": run_url, "dossier": os.path.basename(os.path.normpath(d)),
               "sujet": _clean(req.get("sujet"), 600), "court": _clean(req.get("court"), 80),
               "demontrer": _clean(req.get("demontrer") or req.get("these"), 400), "langue": req.get("langue", "fr"),
               "cibles": [_clean(c, 80) for c in (req.get("cibles") or [])][:8],
               "points": [{"id": p.get("id"), "intitule": _clean(p.get("intitule"), 200)} for p in (req.get("points") or [])][:8]}
    reglages = {"type_par_defaut": "auto", "locuteurs": "auto", "autorite": "forte", "videos_par_recherche": "8",
                "articles_par_recherche": "6", "langs": langs(req.get("langue")), "depuis": "",
                "telecharger_extraits": False, "en_parallele": "2"}
    payload = {"event_type": "osint-finder",
               "client_payload": {"recherches": chaine, "reglages": reglages, "origine": origine}}
    with open(payload_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    with open(os.path.join(d, "finder.json"), "w", encoding="utf-8") as fh:
        json.dump({"recherches": rech, "envoye": payload["client_payload"], "ciblage": info["mode"]}, fh,
                  ensure_ascii=False, indent=1)
    md = ["# Vid-o-presse-finder lancé automatiquement", "",
          f"Ciblage {info['mode']} à partir de ce run ({info['n_cites']} faits cités au script). "
          f"Langues : {reglages['langs']}.", "",
          "| # | Cible | Ce qu'on cherche | Type | Point du script |", "|---|---|---|---|---|"]
    md += [f"| {i} | {r['cible']} | {r['sujet']} | {r['type']} | {r['point'] or '—'} |" for i, r in enumerate(rech, 1)]
    md += ["", "Résultats : dépôt Vid-o-presse-finder, dossier `results/<lot>/` — le lot contient `ORIGINE.json` "
           f"qui renvoie à ce dossier (`{origine['dossier']}`). Le montage (Montage LV final) le reconnaît tout seul.", ""]
    with open(os.path.join(d, "FINDER.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print(f"Recherches Finder ({info['mode']}) :")
    for r in rech:
        print(f"   - {r['cible']} | {r['sujet']} | {r['type']}")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
