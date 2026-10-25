"""Planification, écriture par chapitres et calage exact sur la durée du live."""
from __future__ import annotations

import re

from . import config, llm

MARK = re.compile(r"\[F\d+\]")

DEVICES = [
    "accumulation de chiffres qui cognent, phrases de plus en plus courtes, puis une chute absurde",
    "promesse officielle contre réalité, en miroir, avec un sarcasme glacial entre les deux",
    "compte à rebours date après date, raconté comme la chronique d'un naufrage annoncé",
    "une seule affaire disséquée en gros plan, ton de polar noir, humour de croque-mort",
    "fausse publicité / faux communiqué officiel parodique, puis le fait brut qui le démolit",
    "question au chat, réponse cinglante, puis une analogie absurde qui fait rire jaune",
    "l'addition posée sur la table, façon ticket de caisse de l'apocalypse",
]

STYLE = """STYLE — tu n'es PAS journaliste, tu es un chroniqueur satirique au vitriol (humour noir, choc, mauvaise foi assumée sur le TON, jamais sur les faits) :
- AGRESSIF ET NOIR D'ABORD. Chaque paragraphe frappe : un fait dur, puis une punchline cynique, une ironie glaciale ou une image absurde qui fait rire jaune. Une vanne ou une pique au moins toutes les 2-3 phrases. Zéro paragraphe neutre.
- Outils : sarcasme, antiphrase (« Bravo. Vraiment, chapeau. »), fausse admiration, analogies grotesques, exagération comique manifeste, faux communiqué officiel parodié, humour de croque-mort, chute qui claque. Vocabulaire cru autorisé quand il sert le propos.
- Tu parles AU spectateur (« toi », « vous »), tu le prends à témoin, tu t'indignes, tu te moques des responsables. Voix incarnée, opinion tranchée, jamais le ton d'une dépêche AFP.
- Rythme oral : phrases courtes, ruptures, silences (« ... »), relances. Jamais de pavé monotone ni d'énumération de chiffres sans réaction.
- TICS INTERDITS : « selon X », « d'après X », « affirme X », « la même source » à chaque phrase ; « ALERTE. » / « Retenez ce chiffre. » / « Relisez cette date. » plus d'une fois par chapitre ; résumés plats ; « il est important de noter » ; ton professoral.
- LANGUE : tout le texte est écrit DIRECTEMENT dans la langue du live (français, arabe, italien, anglais…), avec l'humour noir, les expressions, le rythme et les références propres à cette langue — jamais une traduction plate du français. Les exemples ci-dessous montrent le REGISTRE, pas la langue.
- SANS TABOU : aucun sujet, aucun pays, aucun dirigeant, aucun parti, aucune institution (religieuse, militaire, internationale, financière), aucune célébrité ni entreprise n'est épargné ou ménagé. Même férocité quel que soit le camp, le pays ou le bord politique visé : pas de double standard, pas de traitement de faveur.
- Exemple de registre ATTENDU : « Trente pour cent des engrais du monde coincés dans un détroit. Trente. Mais rassure-toi : à Bruxelles, on a créé un groupe de travail. La famine, elle, n'a pas besoin de groupe de travail. Elle est très autonome. »
- Exemple de registre REFUSÉ : « Selon Rabobank, le blocage paralyse 25 à 30 % des exportations d'engrais, d'après les données publiées. »
- Cible les actes, décisions, déclarations et responsabilités de personnes publiques et d'organisations. Jamais d'attaque contre un groupe en raison de son origine, sa religion, son orientation, son handicap. Aucun appel à la violence. L'ironie sur le DÉCALAGE entre le parcours public et documenté d'une personnalité (origines comprises, si les faits sont sourcés) et ses positions ou promesses est permise : elle vise la personne publique et ses actes, jamais un groupe.
- FIDÉLITÉ À LA REQUÊTE : le live défend l'angle exact de l'utilisateur (sujet + thèse), dans ses termes les plus directs. INTERDIT : minimiser cet angle, moraliser, ajouter des précautions oratoires, s'excuser, ou faire la leçon au public. Les faits contraires se traitent par la règle 6, jamais en désamorçant l'angle."""

TRUTH = """RÈGLES DE VÉRITÉ (non négociables) :
1. Toute affirmation factuelle (chiffre, date, nom, décision, citation) vient UNIQUEMENT des FAITS fournis et est suivie de son marqueur [F12] (plusieurs : [F12][F14]).
2. Aucun fait, chiffre, date ou nom hors de la liste. Interdit de combler avec ta mémoire.
3. SOURCES À L'ORAL — le moins possible : les sources complètes sont dans le commentaire épinglé, PAS dans la voix.
   - Fait établi (statut fait, confirmé, source fiable) : énonce-le CASH, sans « selon » ni nom de média. Le marqueur [F12] suffit.
   - Allégation, opinion, accusation, fait contredit ou non corroboré : attribue-le UNE fois, brièvement, à sa PREMIÈRE apparition (« d'après Le Monde », « c'est l'ONU qui le dit »). Les reprises suivantes du même fait n'ont pas besoin d'être réattribuées, sauf s'il vise une personne privée.
   - Au maximum UNE attribution orale toutes les 4-5 phrases. Jamais « la même source », jamais deux médias dans la même phrase.
   - Tu peux transformer l'attribution en arme (« même l'ONU, pas vraiment un repaire d'agitateurs, s'en inquiète »).
4. Humour, indignation, transitions, analyse, métaphores : pas de marqueur, et c'est là que tu te lâches — mais aucun chiffre ni fait réel nouveau dedans (l'exagération manifestement comique reste permise).
5. Tu peux relier les faits (comparaison, contradiction, conséquence logique) en marquant chaque fait mobilisé.
6. Faits "contre" la thèse : mentionne-les honnêtement en une ou deux phrases, puis réponds avec les autres faits. C'est ce qui rend le live inattaquable.
7. Présomption d'innocence dans les passages FACTUELS : enquête, perquisition, mise en examen, plainte ou soupçon ne sont PAS une condamnation. Écris « enquête », « soupçonné de », « visé par » et non « coupable » ou « condamné » comme un fait. Les images, métaphores et punchlines d'humour noir restent autorisées, même sur la justice, tant qu'elles sont manifestement figurées et jamais présentées comme un fait établi."""


# ------------------------------------------------------------------ utilitaires
def clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", MARK.sub("", text)).replace(" ,", ",").replace(" .", ".").strip()


def wc(text: str) -> int:
    return len(clean(text).split())


def score(f) -> int:
    base = f["importance"] * 2 + f["choc"] + (1 if f["pertinence_these"] == "pour" else 0)
    return base - (3 if f.get("verification") == "non_corrobore" else 0)      # fragile ET non confirmé : on le garde, mais moins en avant


def comprehension(ctx) -> str:
    """Ce que la requête veut VRAIMENT démontrer (thèse implicite + raisonnement), surtout utile pour les requêtes longues."""
    c = ctx.get("comprendre") or {}
    rows = []
    if c.get("demontrer"):
        rows.append(f"CE QUE LE LIVE DOIT DÉMONTRER : {c['demontrer']}")
    if c.get("raisonnement"):
        rows.append("RAISONNEMENT DE LA REQUÊTE (à suivre dans cet ordre) : " + " -> ".join(c["raisonnement"]))
    if c.get("cibles"):
        rows.append("RESPONSABLES / CIBLES visés : " + ", ".join(c["cibles"]))
    return "\n".join(rows)


def points_text(ctx) -> str:
    pts = ctx.get("points") or []
    return "\n".join(f"- {x['id']} : {x['intitule']}" for x in pts)


def facts_text(facts) -> str:
    return "\n".join(
        f"[{f['id']}] ({f['type']}, importance {f['importance']}/5, {f['statut']}, fiabilité {f['fiabilite']}, "
        f"{f['pertinence_these'].upper()}{', point ' + f['point'] if f.get('point') else ''}) {f['fact']}"
        + (f" — affirmé par : {f['attribution']}" if f.get("attribution") else "")
        + {"indisponible": " — ⚠ non vérifié : attribue-le UNE fois, brièvement",
           "non_corrobore": " — ⚠ non corroboré : attribue-le UNE fois, brièvement",
           "contredit": " — ⚠ CONTREDIT par une autre source : présente le fait ET la contradiction",
           "confirme": " — confirmé par une source indépendante"}.get(f.get("verification"), "")
        for f in facts)


def select_facts(facts, words, point_ids=()):
    cap = max(6, int(words / config.WORDS_PER_FACT))
    ranked = sorted(facts, key=score, reverse=True)
    chosen = ranked[:cap]
    ids = {f["id"] for f in chosen}
    # un fait d'importance maximale n'est jamais sacrifié (dans la limite de +20 %)
    extra = [f for f in ranked[cap:] if f["importance"] == 5][: max(1, cap // 5)]
    chosen += extra
    ids |= {f["id"] for f in extra}
    for pid in point_ids:        # chaque point de la requête garde au moins ses 3 meilleurs faits
        mine = [f for f in ranked if f.get("point") == pid]
        for f in mine[:3]:
            if f["id"] not in ids:
                chosen.append(f)
                ids.add(f["id"])
    unused = [f for f in ranked if f["id"] not in ids]
    return chosen, unused


# ------------------------------------------------------------------ plan
def plan(ctx, chosen, words):
    n_ch = max(1, min(40, round(words / 700)))
    listing = "\n".join(f"{f['id']} | imp {f['importance']} | choc {f['choc']} | {f['pertinence_these']} | {f['fact'][:180]}"
                        for f in chosen)
    p = f"""Tu es rédacteur en chef d'un live YouTube d'investigation. SUJET : {ctx['sujet']}
THÈSE : {ctx['these'] or '(aucune)'}
{comprehension(ctx)}
{('POINTS DE LA REQUÊTE : ils DOIVENT TOUS être traités. Chaque point a au moins un chapitre qui lui est consacré (ou une partie clairement identifiable), et le titre_live doit refléter la requête sans l\'édulcorer :' + chr(10) + points_text(ctx)) if ctx.get('points') else ''}
Construis le conducteur : {n_ch} chapitre(s) (davantage si nécessaire pour couvrir tous les points), chacun avec un ANGLE distinct (pas de redite, pas de hors-sujet),
dans un ordre qui SUIT LE RAISONNEMENT de la requête (cause -> mécanisme -> conséquences -> responsables -> chute), en faisant monter la tension.
Chaque angle doit être une idée-force satirique, pas une simple rubrique (« Bruxelles organise la pénurie avec un tableur », pas « Les importations »). Répartis TOUS les faits ci-dessous (chacun dans un seul chapitre),
en regroupant ceux qui se répondent.
Réponds en JSON : {{"titre_live": str, "chapitres": [{{"titre": str, "angle": str, "points": ["P1"], "fact_ids": ["F1","F2"]}}]}}

FAITS :
{listing}"""
    try:
        j = llm.ask_json(p, temperature=0.5)
    except RuntimeError as e:
        print(f"   ! plan indisponible ({str(e)[:80]}) : plan par défaut")
        j = None
    j = j if isinstance(j, dict) else {}
    valid = {f["id"] for f in chosen}
    chapters, used = [], set()
    for c in j.get("chapitres") if isinstance(j.get("chapitres"), list) else []:
        if not isinstance(c, dict) or not isinstance(c.get("fact_ids"), list):
            continue
        ids = [i for i in c["fact_ids"] if isinstance(i, str) and i in valid and i not in used]
        used |= set(ids)
        if ids:
            chapters.append({"titre": str(c.get("titre") or "Chapitre"), "angle": str(c.get("angle") or ""), "fact_ids": ids,
                             "points": [x for x in c.get("points", []) if isinstance(x, str)] if isinstance(c.get("points"), list) else []})
    if not chapters:
        chapters = [{"titre": "Le dossier", "angle": "vue d'ensemble", "fact_ids": []}]
    leftovers = [f["id"] for f in chosen if f["id"] not in used]
    for k, i in enumerate(leftovers):
        chapters[k % len(chapters)]["fact_ids"].append(i)
    titre = j.get("titre_live")
    return (titre.strip() if isinstance(titre, str) and titre.strip() else ctx["sujet"]), chapters


# ------------------------------------------------------------------ écriture
SAME_SRC = re.compile(r",?\s*(?:(?:selon|d'après|d’après|affirme)\s+la\s+même\s+source(?:\s+non\s+confirmée)?"
                      r"|according\s+to\s+the\s+same\s+source|secondo\s+la\s+stessa\s+fonte"
                      r"|(?:وفقا|وفقاً|حسب|بحسب)\s+(?:لـ\s*)?(?:ال)?(?:نفس\s+المصدر|المصدر\s+نفسه))", re.I)


def _tidy(text, allowed):
    text = re.sub(r"\b(?:Selon|D'après|D’après|According\s+to|Secondo)\s+(?:la|the)\s+(?:même|same|stessa)\s+(?:source|fonte)(?:\s+non\s+confirmée)?\s*,\s*(\w)",
                  lambda m: m.group(1).upper(), text)
    text = SAME_SRC.sub("", text)
    text = re.sub(r"^\s*#+\s.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M).replace("**", "").replace("__", "")
    text = re.sub(r"\[(F\d+)\]", lambda m: m.group(0) if m.group(1) in allowed else "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write_section(ctx, sec, budget, facts_by_id, prev_tail="", done_titles=(), extra_ids=(), device=""):
    ids = list(sec["fact_ids"]) + list(extra_ids)
    sel = [facts_by_id[i] for i in ids if i in facts_by_id]
    kind = sec["kind"]
    role = {
        "hook": "OUVERTURE : les 20 premières secondes décident de tout. Aucune source citée ici. Commence par le fait le plus violent suivi d'une punchline noire, puis annonce l'angle EXACT "
                "de la requête presque mot pour mot, avec un fait dur pour CHAQUE personne ou point en jeu, et promets ce que le live va démontrer. "
                "Aucune phrase qui relativise ou détourne l'angle. Puis lance le premier chapitre.",
        "chapter": f"CHAPITRE « {sec['titre']} » — angle : {sec.get('angle', '')}. Procédé de rythme : {device}.",
        "outro": "CONCLUSION : rappelle en rafale, SANS citer aucune source, les chiffres les plus lourds (un par personne ou point), reviens à l'angle exact de la requête, "
                 "chute la plus noire et la plus drôle du live, phrase de sortie mémorable, appel court et sarcastique à s'abonner et partager. Pas de nouveau fait hors liste.",
    }[kind]
    extras = []
    if ctx["interactions"] and kind == "chapter":
        extras.append("Intègre un appel naturel au chat (question ou vote) sans casser le rythme.")
    if not ctx["defense"]:
        extras.append("Ignore la règle 6 : ne développe pas les faits 'contre'.")
    current = sec.get("text")
    mode = ""
    if current:
        mode = (f"\nTEXTE ACTUEL (à retravailler) :\n{current}\n\nRéécris-le pour atteindre la longueur demandée. "
                "Pour RACCOURCIR : supprime d'abord redites, digressions et faits d'importance ≤3, jamais ceux d'importance 5. "
                "Pour ALLONGER : ajoute les faits supplémentaires fournis, puis approfondis mécanismes, conséquences et comparaisons "
                "entre faits existants. Jamais de hors-sujet ni de remplissage.")
    fil = ""
    if ctx.get("points"):
        fil = ("\nFIL DE LA REQUÊTE (le live doit honorer chacun de ces points, sans rien inventer ni édulcorer"
               + (f" ; ce chapitre porte surtout sur : {', '.join(sec['points'])}" if sec.get("points") else "") + ") :\n"
               + points_text(ctx) + "\n")
    p = f"""{STYLE}

{TRUTH}

SUJET DU LIVE : {ctx['sujet']}{fil}
THÈSE : {ctx['these'] or '(aucune)'}
{comprehension(ctx)}
LANGUE DU LIVE : {ctx['lang']['nom']} — écris TOUT le texte en {ctx['lang']['nom']} (les faits fournis peuvent être dans une autre langue : traduis-les fidèlement, chiffres et noms intacts).
{role}
{' '.join(extras)}

LONGUEUR : {budget} mots (tolérance ±5 %). Texte parlé continu à lire au téléprompteur, paragraphes courts,
sans titre, sans liste, sans indication de scène.
DÉJÀ TRAITÉ (ne pas répéter) : {', '.join(done_titles) or 'rien'}
FIN DU PASSAGE PRÉCÉDENT (enchaîne naturellement) : {prev_tail[-350:] or '(début du live)'}

FAITS À UTILISER :
{facts_text(sel) or '(aucun fait spécifique : reprends et mets en perspective ceux déjà cités)'}
{mode}
Écris maintenant le texte, rien d'autre."""
    out = _tidy(llm.text(llm.ask(p, temperature=0.95)), set(ids))
    if not current and len(out.split()) < max(8, budget * 0.25):      # réponse vide / bloquée / tronquée : un second essai
        out2 = _tidy(llm.text(llm.ask(p, temperature=1.0)), set(ids))
        if len(out2.split()) > len(out.split()):
            out = out2
    return out


ATTR_MID = re.compile(r",\s*(selon|d'après|d’après|affirme|affirment|rapporte|according\s+to|says|reports|secondo|stando\s+a|riporta)\s+((?:l[ae']\s?|les\s)?[A-ZÉÈÀ][\w.’'\- ]{1,40}?)(?=\s*(?:\[F\d+\])*\s*[,.;!?…])")
ATTR_HEAD = re.compile(r"(^|(?<=[.!?…]\s))(Selon|D'après|D’après|According\s+to|Secondo|Stando\s+a)\s+((?:l[ae']\s?|les\s)?[A-ZÉÈÀ][\w.’'\- ]{1,40}?),\s*(\w)")


ATTR_AR = re.compile(r"[،,]?\s*(?:وفقاً|وفقا|بحسب|حسب|نقلاً\s+عن|نقلا\s+عن)\s+(?:لـ\s*)?([^\s،,.!؟\[]+(?:\s+[^\s،,.!؟\[]+)?)")


def dedup_attributions(secs):
    """Une même source n'est nommée à voix haute qu'une fois dans tout le live : les reprises suivantes sont supprimées."""
    seen = set()

    def key(name):
        return re.sub(r"^(l[ae']\s?|les\s)", "", name.strip().lower())

    def mid(m):
        k = key(m.group(2))
        if k in seen:
            return ""
        seen.add(k)
        return m.group(0)

    def head(m):
        k = key(m.group(3))
        if k in seen:
            return m.group(1) + m.group(4).upper()
        seen.add(k)
        return m.group(0)

    n0 = sum(len(ATTR_MID.findall(x["text"])) + len(ATTR_HEAD.findall(x["text"])) for x in secs)
    for sec in secs:
        t = sec["text"]
        out, pos = [], 0
        for m in sorted(list(ATTR_MID.finditer(t)) + list(ATTR_HEAD.finditer(t)), key=lambda m: m.start()):
            if m.start() < pos:
                continue
            out.append(t[pos:m.start()])
            out.append(mid(m) if m.re is ATTR_MID else head(m))
            pos = m.end()
        out.append(t[pos:])
        sec["text"] = re.sub(r"[ \t]{2,}", " ", "".join(out))
    seen_ar = set()

    def ar(m):
        k = m.group(1)
        if k in seen_ar:
            return ""
        seen_ar.add(k)
        return m.group(0)
    for sec in secs:
        sec["text"] = ATTR_AR.sub(ar, sec["text"])
    n1 = sum(len(ATTR_MID.findall(x["text"])) + len(ATTR_HEAD.findall(x["text"])) for x in secs)
    if n0 != n1:
        print(f"   citations orales répétées supprimées : {n0} -> {n1}")


# ------------------------------------------------------------------ orchestration
def generate(ctx, facts, words):
    by_id = {f["id"]: f for f in facts}
    chosen, unused = select_facts(facts, words, [x["id"] for x in ctx.get("points") or []])
    print(f"   {len(chosen)} faits retenus pour {words} mots ({len(unused)} en réserve)")
    titre, chapters = plan(ctx, chosen, words)

    hook_w = max(45, round(words * 0.05))
    outro_w = max(55, round(words * 0.07))
    body = max(80, words - hook_w - outro_w)
    for c in chapters:
        c["kind"] = "chapter"
        c["weight"] = sum(score(by_id[i]) for i in c["fact_ids"]) + 1
    tot = sum(c["weight"] for c in chapters)
    for c in chapters:
        c["budget"] = round(body * c["weight"] / tot)

    top = sorted(chosen, key=score, reverse=True)[:5]
    best = sorted(chosen, key=score, reverse=True)
    per_point = [next((f for f in best if f.get("point") == x["id"]), None) for x in ctx.get("points") or []]
    per_point = [f["id"] for f in per_point if f]
    hook_ids = list(dict.fromkeys(per_point + [f["id"] for f in top[:2]]))[:6]       # un fait dur par point dans l'ouverture
    outro_ids = list(dict.fromkeys(per_point + [f["id"] for f in top[:3]]))[:6]
    secs = [{"kind": "hook", "titre": "Ouverture", "fact_ids": hook_ids, "budget": hook_w}]
    secs += chapters
    secs += [{"kind": "outro", "titre": "Conclusion", "fact_ids": outro_ids, "budget": outro_w}]

    tail, titles = "", []
    for k, s in enumerate(secs):
        print(f"   écriture : {s['titre']} ({s['budget']} mots)")
        try:
            s["text"] = write_section(ctx, s, s["budget"], by_id, tail, titles,
                                      device=DEVICES[k % len(DEVICES)])
        except (SystemExit, RuntimeError) as e:     # quota/délai : on garde ce qui est déjà écrit
            print(f"   ! écriture interrompue ({str(e)[:110]}) : {len(secs) - k} section(s) non écrite(s)")
            for rest in secs[k:]:
                rest.setdefault("text", "")
            break
        tail = clean(s["text"])
        titles.append(s["titre"])
    secs = [s for s in secs if s.get("text", "").strip()]
    if not secs:
        raise SystemExit("Aucune section n'a pu être écrite (quota ou délai) : les faits et sources restent dans donnees.json.")

    dedup_attributions(secs)
    try:
        fit(ctx, secs, words, by_id, unused)
    except (SystemExit, RuntimeError) as e:
        print(f"   ! calage final interrompu ({str(e)[:100]}) : on garde le texte déjà écrit")
    dedup_attributions(secs)
    return titre, secs


SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def _sentence_value(sent, by_id):
    ids = re.findall(r"\[(F\d+)\]", sent)
    vals = [score(by_id[i]) for i in ids if i in by_id]
    return max(vals) if vals else 4        # phrase sans fait (humour, transition) : valeur moyenne


def _trim(secs, target, by_id, tol):
    """Raccourcit SANS appel LLM : retire d'abord les phrases de moindre valeur (jamais l'ouverture ni la conclusion)."""
    floor = target * (1 - tol)
    total = sum(wc(s["text"]) for s in secs)
    cands = []
    for si, sec in enumerate(secs):
        if sec["kind"] != "chapter":
            continue
        txt = re.sub(r"([.!?…])\s*((?:\[F\d+\])+)", r" \2\1", sec["text"])
        paras = [[x for x in SENT_SPLIT.split(p.strip()) if x] for p in re.split(r"\n\s*\n", txt) if p.strip()]
        sec["_paras"] = paras
        for pi, para in enumerate(paras):
            for k, sent in enumerate(para):
                cands.append((_sentence_value(sent, by_id), -wc(sent), si, pi, k))
    removed = set()
    for val, negw, si, pi, k in sorted(cands):
        w = -negw
        if total - w < floor:
            continue
        if total <= target * (1 + tol / 2):
            break
        removed.add((si, pi, k))
        total -= w
    for si, sec in enumerate(secs):
        if "_paras" not in sec:
            continue
        paras = [[x for k, x in enumerate(para) if (si, pi, k) not in removed] for pi, para in enumerate(sec["_paras"])]
        sec["text"] = "\n\n".join(" ".join(p) for p in paras if p)
        del sec["_paras"]
    return total


def fit(ctx, secs, target, by_id, unused, tol=0.03, rounds=5):
    """Cale le texte sur la durée. Trop long : coupe l'accessoire (sans LLM). Trop court : étoffe par du fond.
    Une réécriture n'est gardée que si elle rapproche vraiment de la cible."""
    for r in range(rounds):
        total = sum(wc(s["text"]) for s in secs)
        diff = target - total
        print(f"   calage {r + 1}: {total}/{target} mots")
        if abs(diff) <= target * tol:
            return
        body = [s for s in secs if s["kind"] == "chapter"] or secs
        if diff < 0:
            now = _trim(secs, target, by_id, tol)
            print(f"   coupe des phrases les moins utiles : {total} -> {sum(wc(s['text']) for s in secs)} mots")
            return
        tw = sum(s.get("weight", 1) for s in body)
        for s in body:
            share = round(diff * s.get("weight", 1) / tw)
            if share < 20:
                continue
            want = wc(s["text"]) + share
            n_extra = min(len(unused), max(0, share // config.WORDS_PER_FACT))
            extra = [unused.pop(0) for _ in range(n_extra)]
            for f in extra:
                by_id[f["id"]] = f
            old = s["text"]
            new = write_section(ctx, s, want, by_id, extra_ids=[f["id"] for f in extra])
            if abs(wc(new) - want) < abs(wc(old) - want):
                s["text"] = new
                s["fact_ids"] = s["fact_ids"] + [f["id"] for f in extra]
            else:
                print("   réécriture écartée (elle s'éloignait de la cible)")
