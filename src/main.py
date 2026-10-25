"""CLI : python -m src.main --sujet "..." --duree 20 [--these "..."]"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from dataclasses import asdict

from . import collect, config, facts as F, llm, report, script, thumb, verify


def slug(s):
    s = unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50].strip("-") or "live"


_D = None          # dossier du run en cours (pour y écrire une trace d'erreur)


def _num(s):
    return float(str(s).replace(",", ".").strip())


def _w(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sujet", required=True)
    ap.add_argument("--duree", type=_num, default=20, help="durée du live en minutes")
    ap.add_argument("--these", default="", help="thèse / angle à étayer (optionnel)")
    ap.add_argument("--langue", default="auto")
    ap.add_argument("--wpm", type=int, default=config.WPM, help="mots par minute")
    ap.add_argument("--no-defense", action="store_true", help="ne pas développer les faits contraires")
    ap.add_argument("--no-verify", action="store_true", help="pas de vérification croisée des faits fragiles")
    ap.add_argument("--no-interactions", action="store_true", help="pas d'appels au chat")
    ap.add_argument("--out", default=os.getenv("OUT_DIR", "prompter"))
    a = ap.parse_args()
    a.sujet = " ".join(a.sujet.split())
    if not a.sujet:
        raise SystemExit("Sujet vide.")
    if not (1 <= a.duree <= 360):
        print(f"  ! durée {a.duree} min hors limites : ramenée entre 1 et 360 min")
        a.duree = min(360.0, max(1.0, a.duree))
    a.wpm = max(60, min(300, a.wpm))

    t0 = time.time()
    lang = config.lang_cfg(a.langue, a.sujet)
    words = round(a.duree * a.wpm)
    ctx = {"sujet": a.sujet, "these": a.these, "lang": lang,
           "defense": not a.no_defense, "interactions": not a.no_interactions}
    print(f"[1/5] Cible : {a.duree} min = {words} mots ({a.wpm} mots/min), langue {lang['nom']}")

    # Budget de temps : la recherche ne doit jamais manger le temps d'écriture (≈ 8 min + 1 min / 1000 mots, à réserver).
    reserve = (8 + words / 1000) * 60

    def late():
        return llm.elapsed() > llm.DEADLINE - reserve

    print("[2/5] Collecte multi-sources…")
    br = collect.analyse_requete(a.sujet, a.these, lang["nom"])
    pts, court = br["points"], br["court"]
    ctx["points"], ctx["court"] = pts, court
    ctx["comprendre"] = {k: br.get(k) for k in ("demontrer", "raisonnement", "cibles")}
    if not a.these and br.get("demontrer"):       # pas de thèse saisie : on prend celle comprise dans la requête
        a.these = ctx["these"] = br["demontrer"]
        print(f"   thèse comprise : {a.these}")
    if br.get("raisonnement"):
        print("   raisonnement : " + " -> ".join(br["raisonnement"]))
    print(f"   requête décomposée en {len(pts)} point(s) ; recherche courte : « {court} »")
    for x in pts:
        print(f"     {x['id']} : {x['intitule']}")
    pq = [x["requetes"][0] for x in pts if x["requetes"]] + [q for x in pts for q in x["requetes"][1:]]
    queries = list(dict.fromkeys(pq + collect.expand_queries(a.sujet, a.these, lang["nom"])))
    print("   requêtes :", " | ".join(queries))
    sources = collect.dedupe(collect.collect_all(court, queries, lang))
    nxt = collect.assign_ids(sources)
    print(f"   {len(sources)} sources uniques ; récupération des textes…")
    collect.enrich(sources, lang)

    global _D
    _D = d = os.path.join(a.out, f"{datetime.datetime.now():%Y-%m-%d_%Hh%M}_{slug(court)}")
    os.makedirs(d, exist_ok=True)
    json.dump({"sources": [asdict(s) for s in sources], "faits": []},
              open(os.path.join(d, "donnees.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("[3/5] Extraction et vérification des faits…")
    facts = F.extract(sources, a.sujet, a.these, points=pts)

    # Un point de la requête sous-documenté ? Recherche ciblée sur CE point avant tout le reste.
    thin = [x for x in pts if sum(1 for f in facts if f.get("point") == x["id"]) < 3]
    if thin and late():
        print("   points sous-documentés : recherche ciblée SAUTÉE (il faut garder le temps d'écrire)")
        thin = []
    if thin:
        print("   points sous-documentés : " + ", ".join(x["id"] for x in thin) + " -> recherche ciblée")
        try:
            tq = []
            for x in thin:
                tq += x["requetes"] or [x["intitule"][:80]]
                tq.append(x["intitule"][:90])
            tq = [q for q in dict.fromkeys(tq) if q not in queries]
            queries += tq
            new = collect.dedupe(collect.collect_all(court, tq, lang, deep=True), known={s.url for s in sources})
            nxt = collect.assign_ids(new, nxt)
            collect.enrich(new, lang)
            more = F.extract(new, a.sujet, a.these, start_id=500, points=pts)
            sources += new
            facts += more
        except (Exception, SystemExit) as e:
            print(f"   ! recherche ciblée interrompue ({str(e)[:100]})")

    # Pas assez de matière pour la durée ? On cherche plus profond, on ne remplit jamais.
    need = int(words / config.WORDS_PER_FACT)
    for rnd in range(2):
        if len(facts) >= need * 0.9:
            break
        if late():
            print("   temps de recherche écoulé : on passe à l'écriture avec les faits déjà vérifiés")
            break
        print(f"   matière insuffisante ({len(facts)}/{need}) -> recherche approfondie {rnd + 1}/2")
        q2 = collect.expand_queries(a.sujet, a.these, lang["nom"], avoid=queries)
        if not q2:
            break
        queries += q2
        try:
            new = collect.dedupe(collect.collect_all(court, q2, lang, deep=True),
                                 known={s.url for s in sources})
            nxt = collect.assign_ids(new, nxt)
            collect.enrich(new, lang)
            more = F.extract(new, a.sujet, a.these, start_id=1000 * (rnd + 1), points=pts)
        except (Exception, SystemExit) as e:
            print(f"   ! recherche approfondie interrompue ({str(e)[:100]}) : on continue avec ce qu'on a")
            break
        sources += new
        facts += more

    if not facts:
        raise SystemExit("Aucun fait exploitable trouvé : vérifie les clés API et reformule le sujet.")
    short = len(facts) < need * 0.6
    if short:
        print(f"   ! matière limitée : {len(facts)} faits pour {need} idéalement ; "
              "le script approfondira l'analyse au lieu de broder.")

    vstats = None
    if not a.no_verify and late():
        print("   vérification croisée SAUTÉE (temps de recherche écoulé)")
    if not a.no_verify and not late():
        print("   Vérification croisée des faits fragiles (source faible, allégation)…")
        try:
            vstats, nxt = verify.corroborate(facts, sources, lang, collect.enrich, collect.assign_ids, nxt)
            print(f"   {vstats['verifies']} faits fragiles vérifiés : {vstats['confirmes']} confirmés par une autre source, "
                  f"{vstats['contredits']} contredits, {vstats['non_corrobores']} non corroborés, {vstats['indisponibles']} non vérifiés")
        except (Exception, SystemExit) as e:
            print(f"   ! vérification croisée interrompue ({str(e)[:100]}) : faits gardés tels quels")
    ctx["vstats"] = vstats

    json.dump({"sources": [asdict(s) for s in sources], "faits": facts},
              open(os.path.join(d, "donnees.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   faits et sources sauvegardés dans {d}/donnees.json (récupérables même si la suite échoue)")

    print("[4/5] Écriture du script…")
    titre, secs = script.generate(ctx, facts, words)
    titre = " ".join(str(titre).split()) or a.sujet

    print("[5/5] Documents de sortie…")
    try:        # liens du commentaire épinglé : on décode les liens Google News encore codés des sources citées
        cited = set(re.findall(r"\[(F\d+)\]", "\n".join(x["text"] for x in secs)))
        sid = {f["source_id"] for f in facts if f["id"] in cited}
        todo = [x for x in sources if x.id in sid and "news.google.com" in x.url]
        for x in todo[:80]:
            x.url = collect.resolve_gnews(x.url)
        if todo:
            print(f"   liens des sources citées : {sum(1 for x in todo[:80] if 'news.google.com' not in x.url)}/{len(todo[:80])} décodés")
    except Exception as e:
        print(f"   ! décodage final des liens ignoré ({str(e)[:80]})")
    clean_txt = "\n\n".join(script.clean(s["text"]) for s in secs)
    annot = f"# {titre}\n\n" + "\n\n".join(f"## {s['titre']}\n\n{s['text']}" for s in secs)
    final_words = len(clean_txt.split())
    stats = {"duree": a.duree, "mots": final_words, "n_sources": len(sources), "n_faits": len(facts)}
    open(os.path.join(d, "script_teleprompter.txt"), "w", encoding="utf-8").write(clean_txt + "\n")
    open(os.path.join(d, "script_annote.md"), "w", encoding="utf-8").write(annot + "\n")
    open(os.path.join(d, "commentaire_epingle.txt"), "w", encoding="utf-8").write(
        report.pinned_comment(titre, secs, facts, sources))
    open(os.path.join(d, "sources.md"), "w", encoding="utf-8").write(
        report.build(titre, secs, facts, sources, ctx, stats))
    json.dump({"sources": [asdict(s) for s in sources], "faits": facts},
              open(os.path.join(d, "donnees.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    problems = []
    if pts:
        used = set(re.findall(r"\[(F\d+)\]", "\n".join(s["text"] for s in secs)))
        rows = ["# Couverture de ta requête", "", f"Requête : {a.sujet}", "",
                "| Point | Faits trouvés | Faits cités dans le script | Chapitres |", "|---|---|---|---|"]
        for x in pts:
            fx = [f for f in facts if f.get("point") == x["id"]]
            cited = [f for f in fx if f["id"] in used]
            chaps = [s["titre"] for s in secs if x["id"] in (s.get("points") or [])]
            rows.append(f"| {x['id']} : {x['intitule']} | {len(fx)} | {len(cited)} | {'; '.join(chaps) or '—'} |")
            if not cited:
                problems.append(f"Point {x['id']} de ta requête (« {x['intitule'][:90]} ») : AUCUN fait cité dans le script "
                                f"({len(fx)} fait(s) trouvé(s)). Source introuvable ou trop faible : précise-le dans le champ thèse ou relance.")
            elif len(cited) < 3:
                problems.append(f"Point {x['id']} (« {x['intitule'][:90]} ») : peu documenté ({len(cited)} fait(s) cité(s)).")
        _w(os.path.join(d, "couverture.md"), "\n".join(rows) + "\n")
    llm.DEADLINE = max(llm.DEADLINE, time.monotonic() - llm.T0 + 240)   # 4 min de grâce pour le titre / la miniature
    print("   Titre + miniature (analyse du top 3 YouTube)…")
    try:
        top_facts = sorted(facts, key=script.score, reverse=True)[:5]
        L, at, am, top3, note = thumb.build(ctx, sources, queries, titre, top_facts)
        open(os.path.join(d, "titre_miniature.md"), "w", encoding="utf-8").write(
            thumb.render(a.sujet, titre, L, at, am, top3, note))
        if L:
            ts = L.get("texte_miniature") or {}
            open(os.path.join(d, "titre.txt"), "w", encoding="utf-8").write((L.get("titre") or "") + "\n")
            open(os.path.join(d, "prompt_miniature.txt"), "w", encoding="utf-8").write((L.get("prompt_image") or "") + "\n")
            open(os.path.join(d, "texte_miniature.txt"), "w", encoding="utf-8").write(
                f"{ts.get('texte', '')}\nCouleur : {ts.get('couleur', '')}\nPolice : {ts.get('police', '')}\n"
                f"Placement : {ts.get('placement', '')}\n")
        print("   titre :", (L or {}).get("titre"), "|", note or "ok")
    except BaseException as e:  # ne jamais perdre le script pour la miniature
        if isinstance(e, KeyboardInterrupt):
            raise
        print(f"   ! titre/miniature non générés : {type(e).__name__}: {str(e)[:150]}")
        problems.append(f"Titre / prompt / texte de miniature NON générés : {type(e).__name__}: {str(e)[:200]}. "
                        "Relance le workflow plus tard (quota Gemini) : le script, lui, est complet.")
        try:
            _w(os.path.join(d, "titre_miniature.md"), "# Titre et miniature\n\n⚠ Non générés : " + problems[-1] + "\n")
        except Exception:
            pass

    if final_words < words * 0.85:
        problems.append(f"Script plus court que la cible : {final_words} mots au lieu de {words} "
                        "(quota ou délai atteint pendant l'écriture, ou matière insuffisante).")
    if final_words > words * 1.15:
        problems.append(f"Script plus long que la cible : {final_words} mots au lieu de {words}.")
    if problems:
        _w(os.path.join(d, "STATUT.txt"), "\n".join("⚠ " + x for x in problems) + "\n")
    est = final_words / a.wpm
    msg = (f"**{titre}**\n\nScript : {final_words} mots ≈ {est:.1f} min (cible {a.duree}) · "
           f"{len(sources)} sources · {len(facts)} faits vérifiés · {round(time.time() - t0)} s"
           + ("\n\n⚠ Matière limitée sur ce sujet." if short else "")
           + "".join("\n\n⚠ " + x for x in problems))
    print("\n" + msg.replace("**", ""))
    print("Fichiers :", d)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(msg + "\n")


def _crash_report(e):
    """Écrit la cause de l'échec dans le dossier du run, pour la lire dans le dépôt sans fouiller les logs."""
    try:
        base = _D or os.getenv("OUT_DIR", "prompter")
        os.makedirs(base, exist_ok=True)
        name = "ERREUR.txt" if _D else f"ERREUR_{datetime.datetime.now():%Y-%m-%d_%Hh%M}.txt"
        _w(os.path.join(base, name), "".join(traceback.format_exception(type(e), e, e.__traceback__))[-3000:])
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None) and not isinstance(e.code, int):
            _crash_report(e)
        raise
    except Exception as e:
        _crash_report(e)
        raise
