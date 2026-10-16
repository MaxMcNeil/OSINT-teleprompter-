"""Extraction des faits : uniquement ce qui est écrit dans les sources, avec contrôle des chiffres."""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import llm

TYPES = "chiffre|date|nom|decision|citation|chronologie|contradiction|contexte"


def nums(text: str) -> set:
    """Nombres de 2 chiffres ou plus, normalisés (espaces/virgules/points retirés)."""
    out = set()
    pat = r"\d{1,3}(?:[\s.,  ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?"
    for m in re.findall(pat, text or ""):
        d = re.sub(r"\D", "", m)
        if len(d) >= 2:
            out.add(d)
    return out


def _block(s) -> str:
    head = f"[{s.id}] ({s.kind} | {s.publisher} | {s.date} | fiabilité {s.meta.get('fiab')})"
    return f"{head} {s.title}\n{s.text[:5000]}"


def _extract_batch(batch, sujet, these, points=()):
    corpus = "\n\n".join(_block(s) for s in batch)
    pts = ("POINTS DE LA REQUÊTE (chaque fait se rattache au point qu'il documente, sinon \"aucun\") :\n"
           + "\n".join(f"{x['id']} : {x['intitule']}" for x in points) + "\n") if points else ""
    p = f"""Tu es analyste OSINT. SUJET : {sujet}
THÈSE À DOCUMENTER : {these or '(aucune, documente le sujet)'}

Extrais des SOURCES ci-dessous les FAITS utiles : chiffres, dates, noms propres, décisions, déclarations exactes,
chronologies, contradictions, promesses et leur suite. Inclus aussi les faits qui CONTREDISENT ou nuancent la thèse.

RÈGLES :
- Uniquement ce qui est écrit explicitement dans la source. Aucun ajout depuis ta mémoire.
- Un fait = une phrase autonome, précise (qui, quoi, combien, quand). Reprends les chiffres tels quels.
- Si la source rapporte une accusation ou une déclaration, mets qui l'affirme dans "attribution".
- Source de fiabilité "faible" (YouTube, X, forums) : statut "signal" ou "allegation", jamais "etabli".
- Ignore le hors-sujet et les faits sans portée.

{pts}
Réponds en JSON : liste d'objets
{{"fact": str, "type": "{TYPES}", "point": "P1|P2|…|aucun", "importance": 1-5, "choc": 1-5,
 "pertinence_these": "pour|contre|neutre", "attribution": str, "statut": "etabli|allegation|opinion|signal",
 "date": str, "source_id": "S12"}}

SOURCES :
{corpus}"""
    j = llm.ask_json(p, temperature=0.1)
    return j if isinstance(j, list) else []


def _str(v):
    return v.strip() if isinstance(v, str) else ""


def _enum(v, allowed, default):
    v = _str(v).lower()
    return v if v in allowed else default


def _int(v, d=3):
    try:
        return max(1, min(5, int(v)))
    except Exception:
        return d


def extract(sources, sujet, these, start_id=1, points=()):
    by_id = {s.id: s for s in sources}
    pts_ids = tuple(x["id"].lower() for x in points)
    ordered = sorted(sources, key=lambda s: ({"haute": 0, "moyenne": 1, "faible": 2}[s.meta["fiab"]], -len(s.text)))
    batches, cur, size = [], [], 0
    for s in ordered[:90]:
        n = min(len(s.text), 5000)
        if cur and (size + n > 48000 or len(cur) >= 14):
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += n
    if cur:
        batches.append(cur)

    def safe_batch(b):
        try:
            return _extract_batch(b, sujet, these, points)
        except (Exception, SystemExit) as e:      # un lot perdu ne doit pas faire perdre les autres
            print(f"   ! lot de {len(b)} sources ignoré : {str(e)[:120]}")
            return []

    with ThreadPoolExecutor(4) as ex:
        results = list(ex.map(safe_batch, batches))

    facts, seen = [], set()
    n = [start_id]
    to_fix = []

    def accept(f, s, txt):
        key = re.sub(r"\W+", "", txt.lower())[:90]
        if key in seen:
            return
        seen.add(key)
        statut = _enum(f.get("statut"), ("etabli", "allegation", "opinion", "signal"), "allegation")
        if s.meta["fiab"] == "faible" and statut == "etabli":
            statut = "signal"
        facts.append({
            "id": f"F{n[0]}", "fact": txt, "type": _enum(f.get("type"), TYPES.split("|"), "contexte"),
            "importance": _int(f.get("importance")), "choc": _int(f.get("choc")),
            "point": _enum(f.get("point"), pts_ids, "").upper(),
            "pertinence_these": _enum(f.get("pertinence_these"), ("pour", "contre", "neutre"), "neutre"),
            "attribution": _str(f.get("attribution")), "statut": statut,
            "date": _str(f.get("date")) or s.date, "source_id": s.id, "fiabilite": s.meta["fiab"],
        })
        n[0] += 1

    for res in results:
        for f in res:
            if not isinstance(f, dict):
                continue
            s = by_id.get(_str(f.get("source_id")))
            txt = _str(f.get("fact"))
            if not s or len(txt) < 15:
                continue
            # Garde-fou : tout nombre du fait doit exister dans la source.
            if nums(txt) <= nums(s.text + " " + s.title):
                accept(f, s, txt)
            else:
                to_fix.append((f, s, txt))

    # Réparation : on redonne au modèle le texte de la source pour corriger le chiffre.
    fixed = dropped = 0
    if to_fix:
        groups = {}
        for t in to_fix:
            groups.setdefault(t[1].id, []).append(t)
        with ThreadPoolExecutor(4) as ex:
            outs = list(ex.map(lambda g: _repair_group(g[0][1], [t[2] for t in g]), list(groups.values())))
        for g, repaired in zip(groups.values(), outs):
            for (f, s, txt), new_txt in zip(g, repaired):
                if new_txt and nums(new_txt) <= nums(s.text + " " + s.title):
                    accept(f, s, new_txt)
                    fixed += 1
                else:
                    dropped += 1
    print(f"   {len(facts)} faits retenus ({fixed} chiffres corrigés d'après la source, "
          f"{dropped} écartés car introuvables)")
    return facts


def _repair_group(s, facts_txt):
    """Corrige, en UN appel par source, les faits dont un chiffre ne figure pas dans la source.
    Renvoie une liste (même longueur) : fait corrigé ou None si la source ne l'établit pas."""
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(facts_txt))
    p = f"""Voici le texte d'une source puis des faits qui en ont été tirés, mais dont un chiffre n'apparaît pas dans la source.
Pour chaque fait, réécris-le avec le chiffre EXACT du texte (même unité, même période). Si la source ne contient pas
de quoi établir ce fait, mets null. N'ajoute rien qui ne soit pas écrit dans la source.

SOURCE ({s.publisher}, {s.date}) :
{s.title}
{s.text[:5000]}

FAITS À CORRIGER :
{numbered}

Réponds en JSON : une liste de {len(facts_txt)} éléments (chaîne ou null), dans le même ordre."""
    try:
        j = llm.ask_json(p, temperature=0.0)
    except (Exception, SystemExit):
        return [None] * len(facts_txt)
    if not isinstance(j, list) or len(j) != len(facts_txt):
        return [None] * len(facts_txt)
    return [x if isinstance(x, str) and x.strip() else None for x in j]
