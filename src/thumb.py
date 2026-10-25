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
Quelles vidéos ci-dessous traitent le même THÈME GÉNÉRAL (mêmes personnes / même affaire / même question), même si l'angle diffère ?
Écarte seulement le hors-sujet évident.
Réponds en JSON : liste des numéros.

{listing}""", temperature=0.0)
        if isinstance(j, list):
            ok = [int(x) for x in j if str(x).isdigit() and int(x) < len(short)]
    except Exception as e:
        print(f"   ! pertinence vidéos par LLM indisponible ({str(e)[:60]}) : repli sur les mots-clés")
    if not ok:      # repli : au moins 2 mots-clés du sujet (1 si le sujet en a peu) dans le titre ou la description
        keys = {w for w in _norm(sujet).split() if len(w) > 3}
        need = 1 if len(keys) <= 3 else 2
        ok = [i for i, v in enumerate(short)
              if keys and len(keys & set(_norm(v["titre"] + " " + v["description"]).split())) >= need]
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


def _s(v):
    return v.strip() if isinstance(v, str) else ""


def _enforce(L, sujet):
    """Respect strict des limites (titre ≤5 mots, texte ≤3 mots, prompt en anglais)."""
    L = dict(L) if isinstance(L, dict) else {}
    tm = L.get("texte_miniature")
    if isinstance(tm, str):
        tm = {"texte": tm}
    tm = tm if isinstance(tm, dict) else {}
    L["texte_miniature"] = {k: _s(tm.get(k)) for k in ("texte", "couleur", "police", "placement")}
    for k in ("titre", "prompt_image", "composition_miniature", "pourquoi_ce_titre"):
        L[k] = _s(L.get(k))
    alts = L.get("titres_alternatifs")
    L["titres_alternatifs"] = [a.strip() for a in alts if isinstance(a, str) and a.strip()][:3] if isinstance(alts, list) else []
    t = L["titre"]
    txt = L["texte_miniature"]["texte"]
    pr = L["prompt_image"]
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
                keep = {k: v for k, v in fix.items() if k != "texte_miniature"}
                L.update(keep)
                if isinstance(fix.get("texte_miniature"), dict):
                    L["texte_miniature"].update({k: _s(v) for k, v in fix["texte_miniature"].items() if k in L["texte_miniature"]})
        except (Exception, SystemExit):
            pass
        for k in ("titre", "prompt_image"):
            L[k] = _s(L.get(k))
    L["titre"] = " ".join(L["titre"].split()[:5])
    L["texte_miniature"]["texte"] = " ".join(_s(L["texte_miniature"].get("texte")).split()[:3])
    return L


def build(ctx, sources, queries, titre_live, top_facts):
    """Retourne (livrables, analyse_titres, analyse_miniatures, top3, note)."""
    sujet = ctx["sujet"]
    hl = ctx["lang"]["hl"]
    try:
        cands = collect.youtube_top(list(dict.fromkeys([ctx.get("court") or sujet] + list(queries[:2]))), hl)
    except Exception as e:
        print(f"   ! YouTube indisponible pour l'analyse ({str(e)[:80]})")
        cands = []
    # on ajoute les vidéos déjà trouvées pendant la collecte (si absentes)
    have = {v["id"] for v in cands}
    for s in sources:
        if s.kind == "youtube" and s.meta.get("video_id") and s.meta["video_id"] not in have and s.meta.get("vues"):
            cands.append({"id": s.meta["video_id"], "titre": s.title, "chaine": s.publisher, "date": s.date,
                          "vues": s.meta["vues"], "duree_min": 0, "description": s.text[:300], "url": s.url})
    top3 = pick_top3(cands, ctx.get("court") or sujet)
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
    j = None
    for attempt_parts in ([parts, []] if parts else [[]]):     # si les images posent problème, on réessaie sans
        try:
            resp = llm.ask([prompt] + attempt_parts, temperature=0.8, json_mode=True, fatal=False)
            j = llm.parse_json(llm.text(resp))
            if isinstance(j, dict) and isinstance(j.get("livrables"), dict):
                break
        except (Exception, SystemExit) as e:
            print(f"   ! titre/miniature : essai échoué ({str(e)[:100]})")
        j = None
    if j is None:
        raise RuntimeError("le modèle n'a pas renvoyé de livrables exploitables")
    if not parts and top3:
        note = "Les miniatures n'ont pas pu être transmises au modèle : analyse faite sur les titres et les chiffres seulement."
    L = _enforce(j["livrables"], sujet)
    at, am = j.get("analyse_titres"), j.get("analyse_miniatures")
    return L, at if isinstance(at, dict) else {}, am if isinstance(am, dict) else {}, top3, note


# Prompt négatif (Midjourney : après --no ; autres IA : « Avoid: ») — n'altère pas le prompt d'origine.
NEGATIF = ("watermark, logo, signature, frame, collage, split screen, cartoon, illustration, painting, plastic skin, "
           "deformed hands, extra fingers, distorted faces, duplicated objects, blurry, low resolution, misspelled text, "
           "extra text, recognizable real person")


def _hex(c):
    m = re.search(r"#?([0-9a-fA-F]{6})\b", c or "")
    return "#" + m.group(1).upper() if m else ""


def prompt_complet(L) -> str:
    """Prompt UNIQUE à coller dans une IA d'image externe (ChatGPT, Gemini, Ideogram…) pour obtenir la miniature
    COMPLÈTE, texte compris. Assemblé sans IA à partir du prompt et du texte d'origine : rien n'est réécrit."""
    tm = L.get("texte_miniature") if isinstance(L.get("texte_miniature"), dict) else {}
    base = re.sub(r"\s*--\w+(\s+[^-\s]\S*)?", "", L.get("prompt_image", "")).strip(" ,.")
    o = [f"YouTube thumbnail, 16:9, 1280x720. {base}."]
    if tm.get("texte"):
        coul = _hex(tm.get("couleur"))
        o.append(f'Add this exact text on the image, spelled exactly, nothing else written: "{tm["texte"]}". '
                 f"Text color: {tm.get('couleur', '')}{' ' + coul if coul and coul not in tm.get('couleur', '') else ''}, "
                 f"bold condensed font ({tm.get('police', 'Anton / Impact')}), thick black outline, "
                 f"placement: {tm.get('placement', 'top left')}. Very large, readable on a phone.")
    o.append("Avoid: " + NEGATIF + ".")
    return " ".join(o)


def render(sujet, titre_live, L, at, am, top3, note, img=None) -> str:
    """UN seul document : titre, composition, prompt complet pour une IA externe (texte compris), prompt d'origine,
    texte incrusté, puis l'analyse du top 3. Le contenu est celui du générateur d'origine, sans changement."""
    tm = L.get("texte_miniature") if isinstance(L.get("texte_miniature"), dict) else {}
    o = [f"# Titre et miniature — {sujet}", ""]
    if note:
        o += [f"> ⚠ {note}", ""]
    o += ["## 1. Titre (3 à 5 mots)", "", f"**{L.get('titre', '')}**", ""]
    if L.get("titres_alternatifs"):
        o += ["Variantes à tester :"] + [f"- {t}" for t in L["titres_alternatifs"]] + [""]
    if L.get("pourquoi_ce_titre"):
        o += [f"Pourquoi : {L['pourquoi_ce_titre']}", ""]
    o += ["## 2. Composition de la miniature", "", L.get("composition_miniature", ""), "",
          "## 3. Prompt complet — à coller dans ChatGPT, Gemini, Ideogram… (miniature finie, texte compris)", "",
          "```", prompt_complet(L), "```", "",
          "Version Midjourney (image seule, texte à ajouter ensuite) :", "", "```", L.get("prompt_image", ""), "```",
          "Prompt négatif (Midjourney : après `--no`) :", "", "```", NEGATIF, "```", "",
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
            if not blk or not isinstance(blk, dict):
                continue
            o += ["", f"### {label}", ""]
            for pv in blk.get("par_video") if isinstance(blk.get("par_video"), list) else []:
                if not isinstance(pv, dict):
                    continue
                detail = "; ".join(f"{k} : {', '.join(map(str, v)) if isinstance(v, list) else v}"
                                   for k, v in pv.items() if k != "rang" and v)
                o.append(f"- Vidéo {pv.get('rang', '?')} — {detail}")
            if isinstance(blk.get("motifs_communs"), list) and blk["motifs_communs"]:
                o += ["", "Motifs communs : " + " ; ".join(map(str, blk["motifs_communs"]))]
            if blk.get("ce_qui_fait_la_difference"):
                o += ["", f"Ce qui fait la différence : {blk['ce_qui_fait_la_difference']}"]
    return "\n".join(o) + "\n"
