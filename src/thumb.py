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


PROMPT = """Rôle : directeur artistique YouTube. Objectif : une miniature qui donne envie de cliquer parce qu'elle est FORTE et VRAIE,
pas parce qu'elle ment. Aucun sujet tabou, aucune censure ; mais rien qui ne soit tenu par les faits du live.

SUJET DU LIVE : {sujet}
TITRE DE TRAVAIL : {titre_live}
LANGUE DU TITRE ET DU TEXTE SUR L'IMAGE : {langue}
FAITS LES PLUS FORTS DU SCRIPT (la miniature doit en porter un) :
{faits}

{bloc_concurrents}

RÈGLES ANTI-PUTACLIC
- Le titre et le texte promettent UNIQUEMENT ce que le live démontre avec les faits ci-dessus.
- Interdits : « CHOC », « INCROYABLE », « VOUS N'ALLEZ PAS CROIRE », « LA VÉRITÉ », emojis, « ?!!! », tout en majuscules dans le titre,
  flèches, cercles rouges, visages surpris, fausse urgence.
- Un chiffre réel ou un fait concret vaut mieux qu'un adjectif.

L'ENJEU CENTRAL D'ABORD (règle n°1, la plus importante)
- Avant tout, écris "idee_centrale" : en une phrase, l'enjeu que le spectateur doit saisir en UNE seconde
  (la conséquence concrète pour les gens, la question brûlante), pas un détail technique du sujet.
- texte_miniature DIT cet enjeu, compréhensible SEUL (sans lire le titre) et reprend un mot-clé du sujet.
  Un chiffre seulement s'il est accompagné de ce qu'il mesure et qu'il frappe (« -40 % D'ENGRAIS »).
  Interdit : un chiffre ou un objet secondaire sans signification seul (ex. « 4 NAVIRES » pour un live sur la famine).
- L'image MONTRE cet enjeu : la conséquence humaine ou concrète, reconnaissable au premier coup d'œil
  (famine → rayons vides, file d'attente pour du pain, champ ravagé ; guerre → lieu ou dirigeant concerné).
  Jamais un objet générique (navire, immeuble, drapeau, salle de réunion) s'il n'est pas lui-même le cœur du sujet.

RÈGLES ANTI-« FAUSSE IA »
- Priorité à une VRAIE photo : donne 4 recherches Wikimedia Commons (en anglais, 2 à 4 mots) qui trouvent une photo réelle et
  libre montrant l'ENJEU CENTRAL (ex. "empty supermarket shelves", "bread queue", "Strait of Hormuz tanker",
  "Giorgia Meloni press conference"), de la plus parlante à la plus générale.
- prompt_image (secours si aucune vraie photo ne convient) : ANGLAIS, style PHOTO DE PRESSE documentaire (Reuters / AP / AFP),
  « shot on 35mm, natural light, slight film grain, realistic colors », une scène simple et crédible, un seul point focal,
  espace vide du côté du texte. AUCUNE personne réelle reconnaissable, pas de visage en gros plan, pas de texte dans l'image.
  BANNIS de ce prompt : 8k, ultra-detailed, hyperrealistic, epic, cinematic masterpiece, apocalyptic, glowing, octane, unreal engine.
- prompt_negatif : ANGLAIS, liste de ce que l'image NE doit PAS contenir (style IA, défauts, éléments hors-sujet).

LIVRABLES
- titre : 3 à 6 mots, net, dans la langue indiquée, + 2 variantes A/B.
- texte_miniature : 1 à 3 mots MAXIMUM, différent du titre (il le complète), dans la langue indiquée ; mot_cle = le mot à colorer ;
  couleur = UN seul code hex d'accent ; zone = "left", "right", "top" ou "bottom" (là où l'image a de l'espace vide).
- concept : une phrase qui décrit l'image idéale.
- lecon_top3 : 1 à 2 phrases, ce qui fait marcher les miniatures concurrentes et ce qu'on en reprend (ou "indisponible").

Réponds UNIQUEMENT en JSON :
{{"livrables": {{"idee_centrale": "", "titre": "", "titres_alternatifs": ["", ""], "texte_miniature": {{"texte": "", "mot_cle": "", "couleur": "#FFD400", "zone": "left"}},
 "concept": "", "recherche_photo": ["", "", "", ""], "prompt_image": "", "prompt_negatif": "", "lecon_top3": ""}}}}"""

NEG_BASE = ("AI-generated look, CGI, 3D render, illustration, painting, plastic skin, oversaturated colors, HDR glow, "
            "fantasy lighting, extra fingers, deformed hands, distorted faces, duplicated objects, gibberish text, letters, "
            "watermark, logo, frame, collage, split screen, arrows, red circles, emoji")


def _s(v):
    return v.strip() if isinstance(v, str) else ""


def _enforce(L, sujet):
    """Respect strict des limites (titre ≤5 mots, texte ≤3 mots, prompt en anglais)."""
    L = dict(L) if isinstance(L, dict) else {}
    tm = L.get("texte_miniature")
    if isinstance(tm, str):
        tm = {"texte": tm}
    tm = tm if isinstance(tm, dict) else {}
    L["texte_miniature"] = {k: _s(tm.get(k)) for k in ("texte", "mot_cle", "couleur", "zone")}
    for k in ("titre", "prompt_image", "prompt_negatif", "concept", "lecon_top3", "idee_centrale"):
        L[k] = _s(L.get(k))
    rp = L.get("recherche_photo")
    L["recherche_photo"] = [q.strip() for q in rp if isinstance(q, str) and q.strip()][:5] if isinstance(rp, list) else []
    alts = L.get("titres_alternatifs")
    L["titres_alternatifs"] = [a.strip() for a in alts if isinstance(a, str) and a.strip()][:3] if isinstance(alts, list) else []
    t = L["titre"]
    txt = L["texte_miniature"]["texte"]
    pr = L["prompt_image"]
    non_ascii = sum(1 for c in pr if ord(c) > 127)
    bad = []
    if _words(t) > 6 or _words(t) < 2:
        bad.append(f"titre ({_words(t)} mots, il en faut 3 à 6)")
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
    L["titre"] = " ".join(L["titre"].split()[:6])
    L["texte_miniature"]["texte"] = " ".join(_s(L["texte_miniature"].get("texte")).split()[:3])
    # mots qui font « image IA » : retirés du prompt ; négatif de base toujours présent
    L["prompt_image"] = re.sub(r",?\s*\b(8k|4k|ultra[- ]detailed|hyper[- ]?realistic|epic|cinematic masterpiece|octane( render)?|"
                               r"unreal engine|trending on artstation)\b", "", L["prompt_image"], flags=re.I)
    L["prompt_image"] = re.sub(r"\s*--\w+\s+\S+", "", L["prompt_image"]).strip(" ,")
    neg = [x.strip() for x in (L["prompt_negatif"] + ", " + NEG_BASE).split(",") if x.strip()]
    L["prompt_negatif"] = ", ".join(dict.fromkeys(neg))
    if not L["recherche_photo"]:
        L["recherche_photo"] = [sujet[:60]]
    L["texte_miniature"]["secours"] = texte_secours(L, sujet)
    if not texte_pertinent(L["texte_miniature"]["texte"], sujet, L):
        old_t = L["texte_miniature"]["texte"]
        L["texte_miniature"]["texte"] = texte_secours(L, sujet)
        L["texte_miniature"]["mot_cle"] = L["texte_miniature"]["texte"].split()[-1] if L["texte_miniature"]["texte"] else ""
        print(f"   texte de miniature « {old_t} » sans rapport clair avec le sujet -> « {L['texte_miniature']['texte']} »")
    return L


_VIDES = set("avec pour dans sans plus moins tout tous toute cette comme mais elle elles nous vous leur leurs sont etre "
             "avoir fait faire quand entre apres avant depuis contre vers chez the and with from that this".split())


def _cles(*textes):
    return {w for t in textes for w in _norm(t or "").split() if len(w) > 3 and w not in _VIDES}


def texte_pertinent(texte, sujet, L) -> bool:
    """Le texte sur l'image doit porter l'enjeu du sujet : au moins un mot-clé du sujet, du titre ou de l'idée centrale
    (racines comparées sur 5 lettres : famine/famines, engrais/engrais…). Un chiffre seul + un mot hors sujet est refusé."""
    mots = _cles(texte)
    if not mots:
        return False
    ref = _cles(sujet, L.get("titre", ""), L.get("idee_centrale", ""))
    rac = {w[:5] for w in ref}
    return any(w[:5] in rac for w in mots)


def texte_secours(L, sujet) -> str:
    """Texte tiré du titre (partie après « : » si elle est courte), sinon les mots forts du sujet."""
    t = L.get("titre", "")
    if ":" in t:
        apres = t.split(":", 1)[1].strip()
        if 1 <= _words(apres) <= 3:
            return apres
    mots = [w for w in re.findall(r"[\w'’-]+", t) if len(w) > 3 and _norm(w).strip() not in _VIDES][:3]
    if mots and texte_pertinent(" ".join(mots), sujet, L):
        return " ".join(mots[-3:])
    mots = [w for w in re.findall(r"[\w'’-]+", sujet) if len(w) > 4 and _norm(w).strip() not in _VIDES]
    return " ".join(mots[:2])


def build(ctx, sources, queries, titre_live, top_facts):
    """Retourne (livrables, top3, note)."""
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
    L = _enforce(j["livrables"], ctx.get("court") or sujet)
    return L, top3, note


def render(sujet, L, top3, note, img=None) -> str:
    """Un seul document, court et actionnable : tout ce qu'il faut pour la miniature et le titre."""
    tm = L.get("texte_miniature") or {}
    zone = {"left": "à gauche", "right": "à droite", "top": "en haut", "bottom": "en bas"}.get(tm.get("zone"), tm.get("zone", ""))
    o = [f"# Miniature — {sujet}", ""]
    if L.get("idee_centrale"):
        o += [f"**Enjeu montré** : {L['idee_centrale']}", ""]
    if img:
        o += ["![miniature](miniature.jpg)", "",
              f"Image : {img['source']}" + (f" · crédit à mettre en description : {img['credit']} ({img['lien']})" if img.get("credit") else ""), ""]
        if img.get("note") is not None:
            o += [f"Contrôle qualité (Gemini, vue mobile) : **{img['note']}/10**"
                  + (f" — {img['probleme']}" if img.get("probleme") else ""), ""]
        if img.get("a_revoir"):
            o += ["> ⚠ Meilleure miniature obtenue mais sous le seuil de qualité : refais-la avec le prompt ci-dessous.", ""]
    else:
        o += ["> ⚠ Image non fabriquée automatiquement : utilise le prompt ci-dessous.", ""]
    if note:
        o += [f"> {note}", ""]
    o += [f"**Titre** : {L.get('titre', '')}",
          f"**Variantes A/B** : {' · '.join(L.get('titres_alternatifs') or []) or '—'}", "",
          f"**Texte sur l'image** : « {tm.get('texte', '')} » — mot en couleur : {tm.get('mot_cle') or '—'} ({tm.get('couleur', '')}) — {zone}",
          "Police : Anton (latin) / Lalezar (arabe), blanc + contour noir, un seul mot en couleur.", "",
          f"**Image** : {L.get('concept', '')}", "",
          "**Prompt** (Midjourney, Ideogram, Flux, Gemini) :", "```", L.get("prompt_image", ""), "```",
          "**Prompt négatif** (Midjourney : à mettre après `--no`) :", "```", L.get("prompt_negatif", ""), "```", "",
          "**À ne pas faire** : texte généré par l'IA dans l'image · visage réel inventé par l'IA · flèches, cercles rouges, emojis · "
          "plus de 3 mots sur l'image · promesse que le live ne tient pas.", ""]
    if top3:
        o += ["**Concurrence (top 3 vues)** :"]
        o += [f"{r}. {v['titre']} — {v['chaine']} — {v['vues']:,} vues".replace(",", " ") for r, v in enumerate(top3, 1)]
        if L.get("lecon_top3"):
            o += ["", f"Ce qu'on en retient : {L['lecon_top3']}"]
    return "\n".join(o) + "\n"
