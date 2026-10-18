"""Document de sources : chaque affirmation du script reliée à son fait, sa source, sa date, son lien."""
from __future__ import annotations

import re

from .facts import nums
from .script import MARK, clean

SENT = re.compile(r"(?<=[.!?…])\s+")


def build(titre, secs, facts, sources, ctx, stats) -> str:
    fb = {f["id"]: f for f in facts}
    sb = {s.id: s for s in sources}
    rows, unsourced, flagged, used_src = [], [], [], {}
    n = 0

    def pool_of(sent):
        ids = re.findall(r"\[(F\d+)\]", sent)
        return " ".join(fb[i]["fact"] + " " + sb[fb[i]["source_id"]].text for i in ids
                        if i in fb and fb[i]["source_id"] in sb)

    for sec in secs:
        txt = re.sub(r"([.!?…])\s*((?:\[F\d+\])+)", r" \2\1", sec["text"])
        for para in re.split(r"\n\s*\n", txt):
            sents = [x for x in SENT.split(para.strip()) if x]
            for k, sent in enumerate(sents):
                ids = list(dict.fromkeys(re.findall(r"\[(F\d+)\]", sent)))
                plain = clean(sent)
                if ids:
                    n += 1
                    cited = [fb[i] for i in ids if i in fb]
                    pool = " ".join(f["fact"] + " " + sb[f["source_id"]].text for f in cited if f["source_id"] in sb)
                    bad = nums(plain) - nums(pool)
                    rows.append((n, sec["titre"], plain, cited, bad))
                    if bad:
                        flagged.append((n, plain, sorted(bad)))
                    for f in cited:
                        used_src[f["source_id"]] = sb.get(f["source_id"])
                elif nums(plain):
                    near = " ".join(pool_of(x) for x in sents[max(0, k - 2):k + 3])   # chiffre repris d'une phrase voisine sourcée
                    if nums(plain) - nums(near):
                        unsourced.append(plain)

    L = [f"# Sources — {titre}", "",
         f"**Sujet** : {ctx['sujet']}  ", f"**Thèse** : {ctx['these'] or '—'}  ",
         f"**Durée** : {stats['duree']} min (~{stats['mots']} mots)  ",
         f"**Corpus** : {stats['n_sources']} sources collectées, {stats['n_faits']} faits vérifiés, "
         f"{len(used_src)} sources citées dans le script", ""]

    L += ["## Points d'attention avant de lancer le live", ""]
    if not flagged and not unsourced:
        L.append("Aucun chiffre sans source détecté.")
    for k, plain, bad in flagged:
        L.append(f"- Affirmation {k} : chiffre(s) {', '.join(bad)} non retrouvé(s) dans la source citée — à vérifier : « {plain[:140]} »")
    for plain in unsourced:
        L.append(f"- Chiffre sans marqueur de source : « {plain[:140]} »")
    figur = re.compile(r"casier|condamn|coupable|voleur|criminel|escroc|corrompu|d[ée]tourn|mafi", re.I)
    for sec in secs:
        for sent in SENT.split(clean(sec["text"])):
            if figur.search(sent):
                L.append(f"- Formulation forte (humour/figuré) : « {sent[:150]} » : OK tant que ça reste clairement une punchline à l'antenne.")
    weak = [r for r in rows if any(f["fiabilite"] == "faible" or f["statut"] in ("allegation", "signal", "opinion") for f in r[3])]
    if weak:
        L.append(f"- {len(weak)} affirmation(s) reposent sur des sources faibles ou des allégations : "
                 "repérées ⚠ ci-dessous, à présenter comme telles à l'antenne.")
    L.append("")

    L += ["## Affirmation par affirmation", ""]
    for k, chap, plain, cited, bad in rows:
        L.append(f"### {k}. {plain}")
        L.append(f"*Chapitre : {chap}*")
        for f in cited:
            s = sb.get(f["source_id"])
            warn = " ⚠" if f["fiabilite"] == "faible" or f["statut"] in ("allegation", "signal", "opinion") else ""
            L.append(f"- **{f['id']}**{warn} {f['fact']}")
            if f.get("attribution"):
                L.append(f"  - Affirmé par : {f['attribution']}")
            if s:
                L.append(f"  - Source : {s.publisher or s.kind} — « {s.title[:110]} » — {s.date or 's.d.'} "
                         f"— fiabilité {s.meta.get('fiab')} — {s.url}")
        if bad:
            L.append(f"- ⚠ Chiffre(s) à revérifier : {', '.join(sorted(bad))}")
        L.append("")

    L += ["## Index des sources citées", ""]
    for sid, s in sorted(used_src.items(), key=lambda kv: int(kv[0][1:])):
        if s:
            L.append(f"- **{sid}** {s.publisher or s.kind} — {s.title[:120]} ({s.date or 's.d.'}) — {s.url}")
    L += ["", "## Faits collectés non utilisés (réserve)", ""]
    cited_ids = {f["id"] for r in rows for f in r[3]}
    for f in sorted(facts, key=lambda f: -(f["importance"] * 2 + f["choc"])):
        if f["id"] not in cited_ids:
            s = sb.get(f["source_id"])
            L.append(f"- {f['id']} {f['fact']} — {(s.publisher if s else '')} {s.url if s else ''}")
    return "\n".join(L) + "\n"


def pinned_comment(titre, secs, facts, sources, max_chars=9000) -> str:
    """Commentaire épinglé YouTube : sources citées dans le script, dans l'ordre d'apparition, avec adresse réelle."""
    fb = {f["id"]: f for f in facts}
    sb = {s.id: s for s in sources}
    order, seen = [], set()
    for sec in secs:
        for fid in re.findall(r"\[(F\d+)\]", sec["text"]):
            f = fb.get(fid)
            s = sb.get(f["source_id"]) if f else None
            if s and s.id not in seen:
                seen.add(s.id)
                order.append(s)
    real = [s for s in order if "news.google.com" not in s.url]
    wrapped = [s for s in order if "news.google.com" in s.url]
    L = [f"📚 SOURCES : {titre}", "Les propos rapportés sont attribués à leurs auteurs.", ""]
    n, used = 0, sum(len(x) + 1 for x in L)
    for s in real + wrapped:
        n += 1
        label = {"youtube": "vidéo", "x": "X", "reddit": "forum"}.get(s.kind, "")
        head = f"[{n}] {s.publisher or s.kind}" + (f" ({label})" if label else "") + (f", {s.date}" if s.date else "")
        title = s.title[:110]
        block = f"{head} : « {title} »\n{s.url}\n"
        if used + len(block) > max_chars:
            L.append(f"… et {len(order) - n + 1} autre(s) source(s) dans le document complet.")
            break
        L.append(block)
        used += len(block) + 1
    return "\n".join(L).strip() + "\n"
