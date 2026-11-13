"""description.txt : titres provocateurs + description YouTube optimisée, tags ET hashtags inclus dans la description.
Une seule requête IA ; en cas d'échec, une version sans IA est écrite quand même (jamais de run cassé)."""
from __future__ import annotations

import re
from collections import Counter

from . import langue, llm, script, structure

MENTION = {
    "fr": ("Les accusations évoquées sont rapportées par la presse et n'ont pas valeur de condamnation. Toute personne citée "
           "bénéficie de la présomption d'innocence et d'un droit de réponse."),
    "en": ("Allegations mentioned are reported by the press and are not proven. Everyone named is presumed innocent "
           "and has a right of reply."),
    "it": ("Le accuse citate sono riportate dalla stampa e non costituiscono condanna. Ogni persona citata gode della "
           "presunzione di innocenza e del diritto di replica."),
    "ar": "الاتهامات المذكورة نقلتها وسائل الإعلام ولا تُعدّ إدانة. كل شخص مذكور يتمتع بقرينة البراءة وبحق الرد.",
}
LIB = {
    "fr": {"sources": "Sources", "decouvrir": "Dans ce live :", "abonne": "Abonnez-vous pour ne rater aucune analyse.",
           "titres": "TITRES (au choix)", "desc": "DESCRIPTION (tags et hashtags inclus, à coller telle quelle)"},
    "en": {"sources": "Sources", "decouvrir": "In this live:", "abonne": "Subscribe so you never miss an analysis.",
           "titres": "TITLES (pick one)", "desc": "DESCRIPTION (tags and hashtags included, paste as is)"},
    "it": {"sources": "Fonti", "decouvrir": "In questa live:", "abonne": "Iscriviti per non perdere nessuna analisi.",
           "titres": "TITOLI (a scelta)", "desc": "DESCRIZIONE (tag e hashtag inclusi, da incollare così)"},
    "ar": {"sources": "المصادر", "decouvrir": "في هذا البث:", "abonne": "اشترك حتى لا يفوتك أي تحليل.",
           "titres": "العناوين (اختر واحداً)", "desc": "الوصف (الوسوم والهاشتاغات مدرجة، انسخه كما هو)"},
}


def _publishers(secs, facts, sources, n=7):
    """Médias réellement cités dans le script, du plus cité au moins cité."""
    fb = {f["id"]: f for f in facts}
    sb = {s.id: s for s in sources}
    c = Counter()
    for sec in secs:
        for i in re.findall(r"\[(F\d+)\]", sec.get("text") or ""):
            s = sb.get(fb.get(i, {}).get("source_id"))
            pub = (s.publisher or "").strip() if s else ""
            if pub and len(pub) < 60 and "google" not in pub.lower():
                c[pub] += 1
    return [p for p, _ in c.most_common(n)]


def _hashtag(t):
    t = re.sub(r"[^\w]", "", "".join(w[:1].upper() + w[1:] for w in str(t).split()))
    return "#" + t if 2 <= len(t) <= 40 else ""


def _sans_ia(ctx, titre, pubs):
    mots = [x["intitule"] for x in ctx.get("points") or []]
    tags = list(dict.fromkeys([ctx.get("court") or ""] + [w for w in re.findall(r"\b[A-ZÉ][\w\-]{2,}\b", " ".join(mots + [titre]))]))
    return {"titres": [titre], "accroche": titre, "decouvrir": mots[:6], "tags": [t for t in tags if t][:25],
            "hashtags": [_hashtag(t) for t in tags[:12] if _hashtag(t)]}


def build(ctx, titre, secs, facts, sources):
    code = ctx["lang"]["code"]
    lib = LIB.get(code, LIB["en"])
    ch = structure.chaine(code)
    pubs = _publishers(secs, facts, sources)
    debut = script.clean("\n\n".join(s["text"] for s in secs[:3]))[:1500]
    pts = "\n".join(f"- {x['intitule']}" for x in ctx.get("points") or [])
    p = f"""Tu es expert YouTube (CTR, SEO, rétention). Live : « {titre} ». Langue : {ctx['lang']['nom']} (TOUT en {ctx['lang']['nom']}).
Chaîne : {ch.get('nom') or '(sans nom)'}.
POINTS DU LIVE :
{pts or '- ' + ctx['sujet'][:300]}
DÉBUT DU SCRIPT :
{debut}

Produis en JSON :
- "titres" : 4 titres YouTube PROVOCATEURS et ORIGINAUX, courts (45 à 70 caractères), qui donnent envie de cliquer sans mentir :
  images fortes, mots qui frappent, tension. Toute accusation non prouvée est posée en QUESTION (« ? ») ou attribuée, jamais affirmée.
  Pas de MAJUSCULES intégrales, pas d'emoji, pas de « CHOC » ni « INCROYABLE ».
- "accroche" : 2 à 3 phrases (les lignes visibles avant « Plus ») qui reprennent le hook du live ; les accusations restent attribuées.
- "decouvrir" : 4 à 6 lignes courtes « ce que vous allez découvrir » (une par affaire / révélation).
- "tags" : 25 à 35 tags de recherche (noms propres, affaires, thèmes, requêtes que les gens tapent CETTE SEMAINE sur ces sujets), sans « # ».
- "hashtags" : 10 à 15 hashtags tendance et précis (avec « # », sans espace), du plus spécifique au plus large.
Format : {{"titres": [str], "accroche": str, "decouvrir": [str], "tags": [str], "hashtags": [str]}}"""
    j = None
    try:
        j = llm.ask_json(p, temperature=0.8)
    except Exception as e:
        print(f"   ! description par IA indisponible ({str(e)[:80]}) : version simple")
    base = _sans_ia(ctx, titre, pubs)
    if isinstance(j, dict):
        for k in base:
            v = j.get(k)
            if k == "accroche" and isinstance(v, str) and v.strip():
                base[k] = " ".join(v.split())
            elif k != "accroche" and isinstance(v, list):
                vals = [" ".join(x.split()) for x in v if isinstance(x, str) and x.strip()]
                if vals:
                    base[k] = vals
    if not langue.paragraphe_ok(base["accroche"], code):       # accroche dans une autre langue : on la traduit
        try:
            t = llm.text(llm.ask(f"Traduis en {ctx['lang']['nom']}, rien d'autre :\n{base['accroche']}", temperature=0.2, fatal=False))
            if t and langue.paragraphe_ok(t, code):
                base["accroche"] = " ".join(t.split())
        except Exception:
            pass
    titres = list(dict.fromkeys(t.strip() for t in base["titres"] if 10 <= len(t.strip()) <= 100))[:4] or [titre]
    tags = list(dict.fromkeys(t.strip(" #,") for t in base["tags"] if t.strip(" #,")))
    if ch.get("nom") and ch["nom"] not in tags:
        tags.append(ch["nom"])
    # le champ « tags » de YouTube Studio est limité à 500 caractères : on garde ce qui tient
    tags_ok, n = [], 0
    for t in tags:
        if n + len(t) + 2 > 490:
            break
        tags_ok.append(t)
        n += len(t) + 2
    hashtags = list(dict.fromkeys(h if h.startswith("#") else _hashtag(h) for h in base["hashtags"]))
    hashtags = [h for h in hashtags if re.fullmatch(r"#[\w]{2,40}", h)][:15]
    if ch.get("nom") and _hashtag(ch["nom"]) and _hashtag(ch["nom"]) not in hashtags:
        hashtags.append(_hashtag(ch["nom"]))

    desc = [base["accroche"], ""]
    if base["decouvrir"]:
        desc += [lib["decouvrir"]] + [f"▸ {x}" for x in base["decouvrir"][:6]] + [""]
    if pubs:
        desc += [f"{lib['sources']} : " + ", ".join(pubs) + "."]
    desc += [MENTION.get(code, MENTION["en"]), "", lib["abonne"] if not ch.get("nom") else
             lib["abonne"].replace(".", "") + f" — {ch['nom']}.", "", ", ".join(tags_ok), "", " ".join(hashtags)]
    out = [f"=== {lib['titres']} ===", ""] + titres + ["", f"=== {lib['desc']} ===", "", "\n".join(desc).strip(), ""]
    return "\n".join(out)
