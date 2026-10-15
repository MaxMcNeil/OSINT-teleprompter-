"""Planification, écriture par chapitres et calage exact sur la durée du live."""
from __future__ import annotations

import re

from . import config, llm

MARK = re.compile(r"\[F\d+\]")

DEVICES = [
    "montée en tension par accumulation de chiffres, phrases de plus en plus courtes",
    "contraste frontal promesse / réalité, en miroir",
    "mini-chronologie : date après date, comme un décompte",
    "une seule affaire disséquée en gros plan, ton de thriller",
    "question lancée au chat puis réponse cinglante avec un fait dur",
    "bilan chiffré brutal, façon addition qu'on pose sur la table",
]

STYLE = """STYLE (live YouTube, texte parlé) :
- Choc frontal, sans langue de bois ni euphémisme. Vocabulaire cru autorisé quand il sert le propos.
- Mélange : gravité d'abord (faits durs, chiffres, dates, noms), humour noir en contrepoint (ironie, sarcasme, chute cynique), alertes ponctuelles ("ALERTE.", "Retenez ce chiffre.", "Relisez cette date.").
- Rythme oral : phrases courtes, ruptures, relances, questions rhétoriques. Jamais de pavé monotone.
- Cible les actes, décisions, déclarations et responsabilités de personnes publiques et d'organisations. Jamais d'attaque contre un groupe en raison de son origine, sa religion, son orientation, son handicap. Aucun appel à la violence."""

TRUTH = """RÈGLES DE VÉRITÉ (non négociables) :
1. Toute affirmation factuelle (chiffre, date, nom, décision, citation) vient UNIQUEMENT des FAITS fournis et est suivie de son marqueur [F12] (plusieurs : [F12][F14]).
2. Aucun fait, chiffre, date ou nom hors de la liste. Interdit de combler avec ta mémoire.
3. Statut allégation / signal / opinion, ou fiabilité faible : attribue clairement ("selon", "affirme", "d'après une vidéo virale"). Jamais présenté comme établi.
4. Humour, indignation, transitions, analyse : pas de marqueur, mais aucun chiffre ni fait nouveau dedans.
5. Tu peux relier les faits (comparaison, contradiction, conséquence logique) en marquant chaque fait mobilisé.
6. Faits "contre" la thèse : mentionne-les honnêtement en une ou deux phrases, puis réponds avec les autres faits. C'est ce qui rend le live inattaquable."""


# ------------------------------------------------------------------ utilitaires
def clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", MARK.sub("", text)).replace(" ,", ",").replace(" .", ".").strip()


def wc(text: str) -> int:
    return len(clean(text).split())


def score(f) -> int:
    return f["importance"] * 2 + f["choc"] + (1 if f["pertinence_these"] == "pour" else 0)


def facts_text(facts) -> str:
    return "\n".join(
        f"[{f['id']}] ({f['type']}, importance {f['importance']}/5, {f['statut']}, fiabilité {f['fiabilite']}, "
        f"{f['pertinence_these'].upper()}) {f['fact']}"
        + (f" — affirmé par : {f['attribution']}" if f.get("attribution") else "")
        for f in facts)


def select_facts(facts, words):
    cap = max(6, int(words / config.WORDS_PER_FACT))
    ranked = sorted(facts, key=score, reverse=True)
    chosen = ranked[:cap]
    ids = {f["id"] for f in chosen}
    # un fait d'importance maximale n'est jamais sacrifié (dans la limite de +20 %)
    extra = [f for f in ranked[cap:] if f["importance"] == 5][: max(1, cap // 5)]
    chosen += extra
    ids |= {f["id"] for f in extra}
    unused = [f for f in ranked if f["id"] not in ids]
    return chosen, unused


# ------------------------------------------------------------------ plan
def plan(ctx, chosen, words):
    n_ch = max(1, min(12, round(words / 700)))
    listing = "\n".join(f"{f['id']} | imp {f['importance']} | choc {f['choc']} | {f['pertinence_these']} | {f['fact'][:180]}"
                        for f in chosen)
    p = f"""Tu es rédacteur en chef d'un live YouTube d'investigation. SUJET : {ctx['sujet']}
THÈSE : {ctx['these'] or '(aucune)'}
Construis le conducteur : {n_ch} chapitre(s), chacun avec un ANGLE distinct (pas de redite, pas de hors-sujet),
dans un ordre qui fait monter la tension jusqu'à la chute. Répartis TOUS les faits ci-dessous (chacun dans un seul chapitre),
en regroupant ceux qui se répondent.
Réponds en JSON : {{"titre_live": str, "chapitres": [{{"titre": str, "angle": str, "fact_ids": ["F1","F2"]}}]}}

FAITS :
{listing}"""
    j = llm.ask_json(p, temperature=0.5) or {}
    valid = {f["id"] for f in chosen}
    chapters, used = [], set()
    for c in j.get("chapitres", []):
        ids = [i for i in c.get("fact_ids", []) if i in valid and i not in used]
        used |= set(ids)
        if ids:
            chapters.append({"titre": c.get("titre", "Chapitre"), "angle": c.get("angle", ""), "fact_ids": ids})
    if not chapters:
        chapters = [{"titre": "Le dossier", "angle": "vue d'ensemble", "fact_ids": []}]
    leftovers = [f["id"] for f in chosen if f["id"] not in used]
    for k, i in enumerate(leftovers):
        chapters[k % len(chapters)]["fact_ids"].append(i)
    return j.get("titre_live", ctx["sujet"]), chapters


# ------------------------------------------------------------------ écriture
def _tidy(text, allowed):
    text = re.sub(r"^\s*#+\s.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.M).replace("**", "").replace("__", "")
    text = re.sub(r"\[(F\d+)\]", lambda m: m.group(0) if m.group(1) in allowed else "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write_section(ctx, sec, budget, facts_by_id, prev_tail="", done_titles=(), extra_ids=(), device=""):
    ids = list(sec["fact_ids"]) + list(extra_ids)
    sel = [facts_by_id[i] for i in ids if i in facts_by_id]
    kind = sec["kind"]
    role = {
        "hook": "OUVERTURE : les 20 premières secondes décident de tout. Commence par le fait le plus violent, pose l'enjeu, "
                "promets ce que le live va démontrer, puis lance le premier chapitre.",
        "chapter": f"CHAPITRE « {sec['titre']} » — angle : {sec.get('angle', '')}. Procédé de rythme : {device}.",
        "outro": "CONCLUSION : rappelle les 3 chiffres/faits les plus lourds, chute cynique, phrase de sortie mémorable, "
                 "appel court à s'abonner et partager. Pas de nouveau fait hors liste.",
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
    p = f"""{STYLE}

{TRUTH}

SUJET DU LIVE : {ctx['sujet']}
THÈSE : {ctx['these'] or '(aucune)'}
LANGUE : {ctx['lang']['nom']}
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
    out = llm.text(llm.ask(p, temperature=0.85))
    return _tidy(out, set(ids))


# ------------------------------------------------------------------ orchestration
def generate(ctx, facts, words):
    by_id = {f["id"]: f for f in facts}
    chosen, unused = select_facts(facts, words)
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
    secs = [{"kind": "hook", "titre": "Ouverture", "fact_ids": [f["id"] for f in top[:2]], "budget": hook_w}]
    secs += chapters
    secs += [{"kind": "outro", "titre": "Conclusion", "fact_ids": [f["id"] for f in top[:3]], "budget": outro_w}]

    tail, titles = "", []
    for k, s in enumerate(secs):
        print(f"   écriture : {s['titre']} ({s['budget']} mots)")
        s["text"] = write_section(ctx, s, s["budget"], by_id, tail, titles,
                                  device=DEVICES[k % len(DEVICES)])
        tail = clean(s["text"])
        titles.append(s["titre"])

    try:
        fit(ctx, secs, words, by_id, unused)
    except (SystemExit, RuntimeError) as e:
        print(f"   ! calage final interrompu ({str(e)[:100]}) : on garde le texte déjà écrit")
    return titre, secs


def fit(ctx, secs, target, by_id, unused, tol=0.04, rounds=3):
    """Cale le texte sur la durée : coupe l'accessoire d'abord, étoffe par du fond jamais du remplissage."""
    for r in range(rounds):
        total = sum(wc(s["text"]) for s in secs)
        diff = target - total
        print(f"   calage {r + 1}: {total}/{target} mots")
        if abs(diff) <= target * tol:
            return
        body = [s for s in secs if s["kind"] == "chapter"] or secs
        if diff < 0:
            remaining = -diff
            for s in sorted(body, key=lambda s: s.get("weight", 0)):
                if remaining <= 0:
                    break
                cut = min(remaining, int(wc(s["text"]) * 0.35))
                if cut < 20:
                    continue
                new_b = wc(s["text"]) - cut
                s["text"] = write_section(ctx, s, new_b, by_id)
                remaining -= cut
        else:
            tw = sum(s.get("weight", 1) for s in body)
            for s in body:
                share = round(diff * s.get("weight", 1) / tw)
                if share < 20:
                    continue
                n_extra = min(len(unused), max(0, share // config.WORDS_PER_FACT))
                extra = [unused.pop(0) for _ in range(n_extra)]
                for f in extra:
                    by_id[f["id"]] = f
                s["text"] = write_section(ctx, s, wc(s["text"]) + share, by_id,
                                          extra_ids=[f["id"] for f in extra])
                s["fact_ids"] = s["fact_ids"] + [f["id"] for f in extra]
