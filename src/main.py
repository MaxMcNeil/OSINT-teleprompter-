"""CLI : python -m src.main --sujet "..." --duree 20 [--these "..."]"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import time
from dataclasses import asdict

from . import collect, config, facts as F, report, script


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50] or "live"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sujet", required=True)
    ap.add_argument("--duree", type=float, default=20, help="durée du live en minutes")
    ap.add_argument("--these", default="", help="thèse / angle à étayer (optionnel)")
    ap.add_argument("--langue", default="auto")
    ap.add_argument("--wpm", type=int, default=config.WPM, help="mots par minute")
    ap.add_argument("--no-defense", action="store_true", help="ne pas développer les faits contraires")
    ap.add_argument("--no-interactions", action="store_true", help="pas d'appels au chat")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()

    t0 = time.time()
    lang = config.lang_cfg(a.langue, a.sujet)
    words = round(a.duree * a.wpm)
    ctx = {"sujet": a.sujet, "these": a.these, "lang": lang,
           "defense": not a.no_defense, "interactions": not a.no_interactions}
    print(f"[1/5] Cible : {a.duree} min = {words} mots ({a.wpm} mots/min), langue {lang['nom']}")

    print("[2/5] Collecte multi-sources…")
    queries = collect.expand_queries(a.sujet, a.these, lang["nom"])
    print("   requêtes :", " | ".join(queries))
    sources = collect.dedupe(collect.collect_all(a.sujet, queries, lang))
    nxt = collect.assign_ids(sources)
    print(f"   {len(sources)} sources uniques ; récupération des textes…")
    collect.enrich(sources, lang)

    print("[3/5] Extraction et vérification des faits…")
    facts = F.extract(sources, a.sujet, a.these)

    # Pas assez de matière pour la durée ? On cherche plus profond, on ne remplit jamais.
    need = int(words / config.WORDS_PER_FACT)
    for rnd in range(2):
        if len(facts) >= need * 0.9:
            break
        print(f"   matière insuffisante ({len(facts)}/{need}) -> recherche approfondie {rnd + 1}/2")
        q2 = collect.expand_queries(a.sujet, a.these, lang["nom"], avoid=queries)
        queries += q2
        new = collect.dedupe(collect.collect_all(a.sujet, q2, lang, deep=True),
                             known={s.url for s in sources})
        nxt = collect.assign_ids(new, nxt)
        collect.enrich(new, lang)
        sources += new
        facts += F.extract(new, a.sujet, a.these, start_id=len(facts) + 1000 * (rnd + 1))

    if not facts:
        raise SystemExit("Aucun fait exploitable trouvé : vérifie les clés API et reformule le sujet.")
    short = len(facts) < need * 0.6
    if short:
        print(f"   ! matière limitée : {len(facts)} faits pour {need} idéalement ; "
              "le script approfondira l'analyse au lieu de broder.")

    d = os.path.join(a.out, f"{datetime.date.today()}_{slug(a.sujet)}")
    os.makedirs(d, exist_ok=True)
    json.dump({"sources": [asdict(s) for s in sources], "faits": facts},
              open(os.path.join(d, "donnees.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"   faits et sources sauvegardés dans {d}/donnees.json (récupérables même si la suite échoue)")

    print("[4/5] Écriture du script…")
    titre, secs = script.generate(ctx, facts, words)

    print("[5/5] Documents de sortie…")
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

    est = final_words / a.wpm
    msg = (f"**{titre}**\n\nScript : {final_words} mots ≈ {est:.1f} min (cible {a.duree}) · "
           f"{len(sources)} sources · {len(facts)} faits vérifiés · {round(time.time() - t0)} s"
           + ("\n\n⚠ Matière limitée sur ce sujet." if short else ""))
    print("\n" + msg.replace("**", ""))
    print("Fichiers :", d)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(msg + "\n")


if __name__ == "__main__":
    main()
