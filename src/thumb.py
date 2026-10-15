"""Titre + miniature à fort impact, calés sur l'analyse des 3 vidéos YouTube les plus vues qui traitent le sujet."""
from __future__ import annotations

import re
import unicodedata

import requests
from google.genai import types

from . import collect, config, llm


def _norm(t):
    return re.sub(r"[^a-z0-9 ]+", " ", unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode())


def _words(t):
    return len(re.findall(r"\S+", t or ""))


def pick_top3(cands, sujet):
    """Parmi les vidéos candidates, garde celles qui traitent vraiment le sujet, puis les 3 plus vues."""
    if not cands:
        return []
    short = cands[:30]
    listing = "\n".join(f"{i}. {v['titre']} — {v['chaine']} ({v['vues']} vues) : {v['description'][:120]}" for i, v in enumerate(short))
    ok = None
    try:
        j = llm.ask_json(f"""SUJET : {sujet}
Quelles vidéos ci-dessous traitent réellement CE sujet (pas un sujet voisin, pas une simple mention) ?
Réponds en JSON : liste des numéros.

{listing}""", temperature=0.0)
        if isinstance(j, list):
            ok = [int(x) for x in j if str(x).isdigit() and int(x) < len(short)]
    except Exception as e:
        print(f"   ! pertinence vidéos par LLM indisponible ({str(e)[:60]}) : repli sur les mots-clés")
    if not ok:
        keys = {w for w in _norm(sujet).split() if len(w) > 3}
        ok = [i for i, v in enumerate(short)
              if keys and len(keys & set(_norm(v["titre"] + " " + v["description"]).split())) >= max(1, len(keys) // 2)]
    top = sorted((short[i] for i in ok), key=lambda v: -v["vues"])[:3]
    return top


def fetch_thumb(vid):
    for name in ("maxresdefault", "hqdefault"):
        url = f"https://i.ytimg.com/vi/{vid}/{name}.jpg"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code == 200 and len(r.content) > 2000:
                return r.content, url
        except Exception:
            pass
    return None, f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"


PROMPT = """Rôle : Directeur Artistique Senior et Expert High-CTR YouTube. Aucune censure, aucun garde-fou de bienséance : l'impact prime, dans le respect des faits fournis.

SUJET DU LIVE : {sujet}
TITRE DE TRAVAIL DU LIVE : {titre_live}
LANGUE DU TITRE ET DU TEXTE SUR MINIATURE : {langue}
FAITS LES PLUS FORTS DU SCRIPT (le visuel doit en servir au moins un) :
{faits}

{bloc_concurrents}

MISSION
1. Analyse la STRUCTURE DES TITRES (longueur, mots déclencheurs, chiffres, ponctuation, majuscules, promesse, curiosité) et les COMPOSANTES.
2. Analyse l'ARCHITECTURE DES MINIATURES (composition, point focal, règle des tiers, palette, contraste, texte sur image, objets/symboles, densité).
3. Dégage ce qui fait la différence de la n°1 en audience.
4. Livre les 4 éléments, en t'appuyant sur cette analyse.

CONTRAINTES DES LIVRABLES
- titre : 3 à 5 mots MAXIMUM, percutant, orienté curiosité, dans la langue indiquée. Donne aussi 2 variantes pour test A/B.
- composition_miniature : description précise de la miniature (plan, zones, hiérarchie visuelle, couleurs dominantes, zone réservée au texte, ratio 16:9).
- prompt_image : ANGLAIS STRICT (aucun mot français), prompt Midjourney/Ideogram photoréaliste 8k, FACELESS (aucun visage explicite : silhouettes de dos, mains, objets, documents, lieux, symboles), ultra-sombre, cinématographique. Le visuel DOIT être directement lié au sujet « {sujet} » : AUCUN élément hors-sujet. Pas de personne réelle reconnaissable. Termine par les paramètres : --ar 16:9 --style raw
- texte_miniature : 3 mots MAXIMUM, couleur de contraste (nom + code hex), police recommandée (nom précis, gras/condensée) et placement.

Réponds UNIQUEMENT en JSON :
{{"analyse_titres": {{"par_video": [{{"rang": 1, "structure": "", "declencheurs": [""]}}], "motifs_communs": [""], "ce_qui_fait_la_difference": ""}},
 "analyse_miniatures": {{"par_video": [{{"rang": 1, "architecture": "", "palette": "", "texte_sur_image": "", "point_focal": ""}}], "motifs_communs": [""], "ce_qui_fait_la_difference": ""}},
 "livrables": {{"titre": "", "titres_alternatifs": ["", ""], "pourquoi_ce_titre": "", "composition_miniature": "", "prompt_image": "",
               "texte_miniature": {{"texte": "", "couleur": "", "police": "", "placement": ""}}}}}}"""


def _enforce(L, sujet):
    """Respect strict des limites (titre ≤5 mots, texte ≤3 mots, prompt en anglais)."""
    t = L.get("titre", "")
    txt = L.get("texte_miniature", {}).get("texte", "")
    pr = L.get("prompt_image", "")
    non_ascii = sum(1 for c in pr if ord(c) > 127)
    bad = []
    if _words(t) > 5 or _words(t) < 2:
        bad.append(f"titre ({_words(t)} mots, il en faut 3 à 5)")
    if _words(txt) > 3:
        bad.append(f"texte_miniature ({_words(txt)} mots, 3 maximum)")
    if non_ascii > 3 or re.search(r"\b(le|la|les|des|une|avec|pour|sur)\b", pr.lower()):
        bad.append("prompt_image (doit être en anglais strict)")
    if bad:
        try:
            fix = llm.ask_json(f"Corrige uniquement ces points : {'; '.join(bad)}.\nJSON actuel : {L}\n"
                               "Renvoie le MÊME JSON complet corrigé.", temperature=0.3)
            if isinstance(fix, dict) and "titre" in fix:
                L.update(fix)
        except Exception:
            pass
    L["titre"] = " ".join(L.get("titre", "").split()[:5])
    if isinstance(L.get("texte_miniature"), dict):
        L["texte_miniature"]["texte"] = " ".join(L["texte_miniature"].get("texte", "").split()[:3])
    return L


def build(ctx, sources, queries, titre_live, top_facts):
    """Retourne (livrables, analyse_titres, analyse_miniatures, top3, note)."""
    sujet = ctx["sujet"]
    hl = ctx["lang"]["hl"]
    cands = collect.youtube_top([sujet] + list(queries[:2]), hl)
    # on ajoute les vidéos déjà trouvées pendant la collecte (si absentes)
    have = {v["id"] for v in cands}
    for s in sources:
        if s.kind == "youtube" and s.meta.get("video_id") and s.meta["video_id"] not in have and s.meta.get("vues"):
            cands.append({"id": s.meta["video_id"], "titre": s.title, "chaine": s.publisher, "date": s.date,
                          "vues": s.meta["vues"], "duree_min": 0, "description": s.text[:300], "url": s.url})
    top3 = pick_top3(cands, sujet)
    note = ""
    parts, bloc = [], ""
    if top3:
        lines = []
        for r, v in enumerate(top3, 1):
            data, url = fetch_thumb(v["id"])
            v["thumb_url"] = url
            if data:
                parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
            lines.append(f"VIDÉO n°{r} (miniature = image n°{r} ci-jointe) : « {v['titre']} » | chaîne : {v['chaine']} | "
                         f"{v['vues']:,} vues | publiée le {v['date']} | durée {v['duree_min']} min".replace(",", " "))
        bloc = "LES 3 VIDÉOS LES PLUS VUES SUR LE SUJET :\n" + "\n".join(lines)
    else:
        note = ("Aucune vidéo concurrente exploitable (clé YT_API_KEY absente, quota ou aucun résultat pertinent) : "
                "livrables produits à partir du sujet et des faits seulement, sans analyse d'audience.")
        bloc = ("AUCUNE VIDÉO CONCURRENTE DISPONIBLE : laisse 'par_video' vide, mets 'indisponible' dans les motifs, "
                "et conçois les livrables d'après les meilleures pratiques High-CTR et les faits.")
    faits = "\n".join(f"- {f['fact']}" for f in top_facts) or "- (aucun)"
    prompt = PROMPT.format(sujet=sujet, titre_live=titre_live, langue=ctx["lang"]["nom"], faits=faits, bloc_concurrents=bloc)
    resp = llm.ask([prompt] + parts, temperature=0.8, json_mode=True, fatal=False)
    j = llm.parse_json(llm.text(resp))
    L = _enforce(j.get("livrables", {}), sujet)
    return L, j.get("analyse_titres", {}), j.get("analyse_miniatures", {}), top3, note


def render(sujet, titre_live, L, at, am, top3, note) -> str:
    tm = L.get("texte_miniature", {}) if isinstance(L.get("texte_miniature"), dict) else {}
    o = [f"# Titre et miniature — {sujet}", ""]
    if note:
        o += [f"> ⚠ {note}", ""]
    o += ["## 1. Titre (3 à 5 mots)", "", f"**{L.get('titre', '')}**", ""]
    if L.get("titres_alternatifs"):
        o += ["Variantes à tester :"] + [f"- {t}" for t in L["titres_alternatifs"]] + [""]
    if L.get("pourquoi_ce_titre"):
        o += [f"Pourquoi : {L['pourquoi_ce_titre']}", ""]
    o += ["## 2. Composition de la miniature", "", L.get("composition_miniature", ""), "",
          "## 3. Prompt Midjourney / Ideogram (anglais)", "", "```", L.get("prompt_image", ""), "```", "",
          "## 4. Texte incrusté sur la miniature", "",
          f"- Texte : **{tm.get('texte', '')}**", f"- Couleur : {tm.get('couleur', '')}",
          f"- Police : {tm.get('police', '')}", f"- Placement : {tm.get('placement', '')}", ""]
    if top3:
        o += ["---", "", "## Analyse du top 3 (audience)", ""]
        for r, v in enumerate(top3, 1):
            o.append(f"{r}. **{v['titre']}** — {v['chaine']} — {v['vues']:,} vues — {v['date']}".replace(",", " "))
            o.append(f"   - Vidéo : {v['url']}")
            o.append(f"   - Miniature : {v.get('thumb_url', '')}")
        for label, blk in (("Titres", at), ("Miniatures", am)):
            if not blk:
                continue
            o += ["", f"### {label}", ""]
            for pv in blk.get("par_video", []):
                detail = "; ".join(f"{k} : {', '.join(v) if isinstance(v, list) else v}" for k, v in pv.items() if k != "rang" and v)
                o.append(f"- Vidéo {pv.get('rang', '?')} — {detail}")
            if blk.get("motifs_communs"):
                o += ["", "Motifs communs : " + " ; ".join(blk["motifs_communs"])]
            if blk.get("ce_qui_fait_la_difference"):
                o += ["", f"Ce qui fait la différence : {blk['ce_qui_fait_la_difference']}"]
    return "\n".join(o) + "\n"
