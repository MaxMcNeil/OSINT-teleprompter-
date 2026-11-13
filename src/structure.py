"""Style « expert » (défaut) : squelette du live, citation d'ouverture vérifiée, accueil de la chaîne, anti-répétition.

Squelette : hook choc -> citation (auteur réel, vérifiée) -> accueil de la chaîne + programme (le meilleur gardé pour la fin)
-> actes -> « je relie les points » -> conclusion qui reprend la citation.
Chaque étape a un repli : rien ici ne peut faire échouer un run.
"""
from __future__ import annotations

import re
import unicodedata

from . import llm

# ------------------------------------------------------------------ chaînes (accueil + signature, par langue)
# Le logo/nom d'une chaîne ne sert que pour les vidéos dans SA langue. Langue sans chaîne : accueil sans nom.
CHAINES = {
    "fr": {"nom": "Le Journal du NON",
           "accueil": "Bienvenue dans le Journal du NON, et la réponse est Non.",
           "signature": "On se retrouve très vite dans le Journal du NON."},
    "ar": {"nom": "Gulf think-tank",
           "accueil": "أهلاً بكم في Gulf think-tank.",
           "signature": "نلتقي قريباً جداً على Gulf think-tank."},
}


def chaine(code):
    return CHAINES.get(code) or {}


STYLE_EXPERT = """LANGUE DE SORTIE : uniquement la LANGUE DU LIVE indiquée plus bas. Ces consignes et leurs exemples sont en français
pour décrire le REGISTRE : n'écris JAMAIS en français si le live est dans une autre langue, et ne mélange jamais deux langues.
STYLE — tu es un EXPERT GÉOPOLITIQUE et analyste chevronné qui présente un live choc, pas un journaliste de dépêche :
- Chaque paragraphe suit la mécanique : FAIT DUR (daté, chiffré, nommé) -> ANALYSE D'EXPERT (pourquoi, comment, à qui ça profite, quel précédent, quelle conséquence en chaîne) -> PUNCHLINE d'humour noir ou alarmiste qui claque. Zéro paragraphe neutre.
- Tu montres ton niveau : corrélations, interconnexions, rapports de force, intérêts cachés, effets de second ordre. Tu relies une affaire à une autre quand les faits le permettent.
- Humour noir ET alarmiste : ironie glaciale, image absurde, chute qui fait rire jaune, mais toujours au service de l'analyse. Pas de vulgarité gratuite.
- Rétention : relances et boucles ouvertes (« et ce n'est pas le pire », « gardez ce nom en tête, il revient à la fin »), phrases courtes, ruptures, questions au spectateur. Tu parles AU spectateur (« vous »).
- Français courant (ou langue du live) : clair, oral, direct, pas de jargon sans explication.
- Chaque punchline est NEUVE : jamais deux fois la même formule, la même vanne ou la même tournure d'ironie dans le live (« Bravo, chapeau », « mais rassurez-vous », « dormez tranquilles » : au plus UNE fois en tout).
- TICS INTERDITS : « selon X » à chaque phrase, « la même source », résumés plats, « il est important de noter », ton professoral, énumérations de chiffres sans analyse.
- LANGUE : tout le texte est écrit DIRECTEMENT dans la langue du live, avec ses expressions et son rythme — jamais une traduction plate.
- SANS TABOU, sans double standard : même exigence quel que soit le pays, le camp, le dirigeant, l'entreprise ou l'institution.
- Cible les actes, décisions et déclarations de personnes publiques et d'organisations. Jamais d'attaque contre un groupe en raison de son origine, sa religion, son orientation, son handicap. Aucun appel à la violence.
- Exemple de registre ATTENDU : « L'homme qui fabrique le cerveau de l'IA mondiale fréquentait une femme que Washington soupçonne d'espionnage. Si c'était un scénario de film, on le refuserait pour manque de subtilité. Pas besoin de voler des plans quand on peut lire dans la tête du patron. »
- Exemple de registre REFUSÉ : « Selon le New York Times, les services de renseignement estiment que Mme Huang aurait transmis des informations, d'après des sources. »
- FIDÉLITÉ À LA REQUÊTE : l'angle de l'utilisateur est défendu tel quel, sans moraliser ni s'excuser. Les faits contraires se traitent par la règle 6."""

DEVICES_EXPERT = [
    "fait brut, puis « pourquoi c'est grave » en trois phrases d'analyse, puis une image absurde",
    "chronologie serrée date après date, puis la conséquence que personne n'a vue venir",
    "« à qui profite le crime » : les gagnants et les perdants, chiffres à l'appui",
    "le décor qui fait peur : le contexte qui transforme un fait divers en affaire d'État",
    "promesse officielle contre réalité documentée, en miroir, puis la chute",
    "effet domino : un fait, ses conséquences en chaîne jusqu'au portefeuille du spectateur",
    "le détail que tout le monde a raté, puis pourquoi il change tout",
]


# ------------------------------------------------------------------ citation d'ouverture
# Repli sûr (citations attestées, sources classiques) si la proposition de l'IA ne peut pas être vérifiée.
CITATIONS = [
    {"citation": "Toute guerre est fondée sur la tromperie.", "auteur": "Sun Tzu", "source": "L'Art de la guerre",
     "themes": "guerre espion espionnage renseignement ruse tromperie chine strategie militaire secret"},
    {"citation": "Les forts font ce qu'ils peuvent, et les faibles subissent ce qu'ils doivent.", "auteur": "Thucydide",
     "source": "La Guerre du Péloponnèse", "themes": "puissance empire domination rapport de force faible diplomatie hegemonie sanctions"},
    {"citation": "La guerre n'est que la simple continuation de la politique par d'autres moyens.", "auteur": "Carl von Clausewitz",
     "source": "De la guerre", "themes": "guerre politique conflit armee iran ukraine russie israel otan"},
    {"citation": "La raison du plus fort est toujours la meilleure.", "auteur": "Jean de La Fontaine",
     "source": "Le Loup et l'Agneau", "themes": "injustice force pouvoir loi plus fort droit"},
    {"citation": "Il n'y a point de plus cruelle tyrannie que celle que l'on exerce à l'ombre des lois et avec les couleurs de la justice.",
     "auteur": "Montesquieu", "source": "Considérations sur les causes de la grandeur des Romains",
     "themes": "justice loi tribunal tyrannie etat droit proces censure liberte"},
    {"citation": "Le pouvoir tend à corrompre, et le pouvoir absolu corrompt absolument.", "auteur": "Lord Acton",
     "source": "lettre de 1887", "themes": "corruption pouvoir scandale dirigeant president abus affaire"},
    {"citation": "Mais qui gardera les gardiens ?", "auteur": "Juvénal", "source": "Satires",
     "themes": "surveillance police controle frontiere securite gardien agence"},
    {"citation": "Il y a quelque chose de pourri au royaume de Danemark.", "auteur": "Shakespeare", "source": "Hamlet",
     "themes": "scandale pourri crise corruption etat royaume gouvernement"},
    {"citation": "L'homme est né libre, et partout il est dans les fers.", "auteur": "Jean-Jacques Rousseau",
     "source": "Du contrat social", "themes": "liberte peuple oppression droits immigration servitude"},
    {"citation": "Les hommes en général jugent plus par les yeux que par les mains.", "auteur": "Machiavel", "source": "Le Prince",
     "themes": "apparence communication propagande image election mensonge politique"},
    {"citation": "Ceux qui vivent, ce sont ceux qui luttent.", "auteur": "Victor Hugo", "source": "Les Châtiments",
     "themes": "lutte resistance peuple greve revolte combat"},
    {"citation": "Le prix de la grandeur, c'est la responsabilité.", "auteur": "Winston Churchill", "source": "discours à Harvard, 1943",
     "themes": "responsabilite dirigeant crise economie bourse marche puissance"},
]

ATTRIB = {
    "fr": "C'est {auteur}, {source}.",
    "en": "That's {auteur}, {source}.",
    "it": "Parola di {auteur}, {source}.",
    "es": "Lo dijo {auteur}, {source}.",
    "de": "Das sagte {auteur}, {source}.",
    "pt": "Quem disse foi {auteur}, {source}.",
    "ar": "قالها {auteur}، في {source}.",
}


def _norm(t):
    """Normalisation valable pour TOUTES les écritures (latin, arabe…) : minuscules, sans accents ni signes diacritiques
    arabes, sans tatweel, variantes de lettres arabes unifiées."""
    t = unicodedata.normalize("NFKD", str(t).lower())
    t = "".join(c for c in t if not unicodedata.combining(c)).replace("ـ", "")
    t = t.translate(str.maketrans({"ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}))
    return re.sub(r"[^\w ]+|_", " ", t)


def _repli(ctx):
    """Citation sûre la plus proche du sujet (mots-clés), traduite si le live n'est pas en français."""
    words = set(_norm(ctx["sujet"] + " " + (ctx.get("these") or "") + " "
                      + " ".join(x["intitule"] for x in ctx.get("points") or [])).split())
    best = max(CITATIONS, key=lambda c: len(words & set(c["themes"].split())))
    c = dict(best)
    if ctx["lang"]["code"] != "fr":
        try:
            j = llm.ask_json(f"Traduis fidèlement en {ctx['lang']['nom']} (traduction usuelle si elle existe), nom de l'auteur compris "
                             f"(graphie usuelle dans cette langue). JSON {{\"citation\": str, \"auteur\": str, \"source\": str}}.\n"
                             f"Citation : {c['citation']}\nAuteur : {c['auteur']}\nŒuvre : {c['source']}",
                             temperature=0.1)
            if isinstance(j, dict) and isinstance(j.get("citation"), str) and j["citation"].strip():
                c["citation"] = j["citation"].strip()
                c["source"] = str(j.get("source") or c["source"]).strip()
                c["auteur"] = str(j.get("auteur") or c["auteur"]).strip()
        except Exception as e:
            print(f"   ! traduction de la citation indisponible ({str(e)[:60]})")
            return None
    c["verifiee"] = "liste sûre"
    return c


def _verifier(c):
    """Vérifie l'attribution avec la recherche Google de Gemini. True / False / None (vérification impossible)."""
    p = (f"Vérifie avec une recherche web : la citation « {c['citation']} » est-elle AUTHENTIQUEMENT de {c['auteur']} "
         f"({c['source']}), et non une citation apocryphe ou mal attribuée ? Une traduction usuelle fidèle compte comme authentique. "
         "Réponds sur la première ligne uniquement par OUI ou NON, puis une phrase de justification.")
    try:
        t = llm.text(llm.ask(p, temperature=0.0, search=True, retries=3, fatal=False))
    except Exception as e:
        print(f"   ! vérification de la citation impossible ({str(e)[:60]})")
        return None
    first = (t.strip().splitlines() or [""])[0].upper()
    if "OUI" in first or "YES" in first:
        return True
    if "NON" in first or "NO" in first:
        return False
    return None


def citation(ctx):
    """Citation d'ouverture chic / émouvante, d'un auteur réel, vérifiée. Repli : liste sûre. None si tout échoue."""
    pts = "\n".join(f"- {x['intitule']}" for x in ctx.get("points") or [])
    p = f"""Live YouTube d'analyse géopolitique. SUJET : {ctx['sujet']}
ANGLE : {ctx.get('these') or '(aucun)'}
POINTS :
{pts or '(aucun)'}
Propose 3 citations célèbres pour OUVRIR le live et annoncer la couleur (chic, forte ou émouvante), qui éclairent le fond du sujet
(ruse, pouvoir, guerre, argent, trahison, justice…). Règles STRICTES :
- citations RÉELLES, mot pour mot, d'auteurs réels, attribution certaine et vérifiable (classiques, philosophes, stratèges, écrivains,
  hommes d'État). Aucune citation apocryphe, « attribuée à », ni inventée. Moins de 30 mots chacune.
- pas d'auteur vivant cité sur sa propre affaire ; pas de paroles de chanson ni de poème entier.
- "citation", "auteur" et "source" écrits en {ctx['lang']['nom']} (traduction usuelle, graphie usuelle du nom de l'auteur).
Réponds en JSON : [{{"citation": str, "auteur": str, "source": "œuvre ou circonstance (+ année si connue)", "pourquoi": str}}]"""
    try:
        cands = llm.ask_json(p, temperature=0.7)
    except Exception as e:
        print(f"   ! citations non proposées ({str(e)[:60]})")
        cands = None
    if isinstance(cands, dict):
        cands = next((v for v in cands.values() if isinstance(v, list)), [])
    cands = [c for c in (cands or []) if isinstance(c, dict) and all(isinstance(c.get(k), str) and c[k].strip()
                                                                   for k in ("citation", "auteur", "source"))]
    for c in cands[:3]:
        c = {k: " ".join(c[k].split()).strip(" «»\"“”") for k in ("citation", "auteur", "source")}
        if len(c["citation"].split()) > 40:
            continue
        ok = _verifier(c)
        if ok:
            c["verifiee"] = "vérifiée par recherche web"
            print(f"   citation : « {c['citation']} » — {c['auteur']} (vérifiée)")
            return c
        if ok is None:          # vérification impossible (quota) : on ne prend pas de risque, liste sûre
            break
        print(f"   citation écartée (attribution non confirmée) : {c['auteur']}")
    c = _repli(ctx)
    if c:
        print(f"   citation (liste sûre) : « {c['citation']} » — {c['auteur']}")
    return c


def citation_text(c, code):
    return f"« {c['citation']} » " + ATTRIB.get(code, ATTRIB["en"]).format(auteur=c["auteur"], source=c["source"])


# ------------------------------------------------------------------ rôles des sections (style expert)
def role(kind, sec, ctx, device=""):
    cit = ctx.get("citation")
    ch = chaine(ctx["lang"]["code"])
    if kind == "hook":
        return ("HOOK ULTRA-CHOC (avant la citation) : 3 à 6 phrases courtes, AUCUNE source citée, aucune salutation. "
                "Le fait le plus explosif d'abord, puis un deuxième qui aggrave, puis une phrase qui promet la révélation la plus forte "
                "« à la fin » (boucle ouverte). Pas de titre, pas de « bonjour ». Le spectateur doit ne plus pouvoir partir.")
    if kind == "citation":
        return (f"PONT APRÈS LA CITATION : la citation « {cit['citation']} » ({cit['auteur']}) vient d'être lue. Écris SEULEMENT 2 à 3 phrases "
                "qui la relient au sujet du live (contexte de l'auteur, puis « X siècles plus tard… »), sans répéter la citation, "
                "sans fait chiffré, sans saluer le public.")
    if kind == "programme":
        acts = "\n".join(f"- {t}" for t in sec.get("actes") or [])
        return ("PROGRAMME (juste après l'accueil de la chaîne, déjà écrit, ne le répète pas) : en 4 à 7 phrases rapides, annonce "
                "ce que le live va révéler, acte par acte, comme des titres choc (sans numéroter « acte 1 »)"
                + (f", et garde le meilleur pour la fin : « {sec['teaser']} »" if sec.get("teaser") else ", et garde la révélation la plus forte pour la fin")
                + ". Termine par l'équivalent, dans la langue du live, de « restez jusqu'au bout, tout est lié ». Pas de salutation.\nACTES :\n" + acts)
    if kind == "chapter":
        return (f"ACTE « {sec['titre']} » — angle : {sec.get('angle', '')}. Procédé : {device}. "
                "Ouvre l'acte par une transition qui accroche, dans la langue du live (sur le modèle de « Deuxième acte… », « Pendant ce temps… »), "
                "termine par une relance vers la suite.")
    if kind == "liens":
        return ("JE RELIE LES POINTS : le passage qui montre ton niveau d'analyste. Annonce-le dans la langue du live (sur le modèle de « Et maintenant, je relie les points »), puis "
                "« premier point… deuxième point… troisième point… » (traduits) : les "
                "corrélations, interconnexions, causes communes, à qui tout cela profite, le fil rouge qui unit les actes du live. "
                "Uniquement des liens logiques entre les faits fournis (marqués) — aucun fait nouveau. Finis sur une phrase choc.\n"
                "ACTES DU LIVE :\n" + "\n".join(f"- {t}" for t in sec.get("actes") or []))
    if kind == "outro":
        return ("CONCLUSION : " + (f"reprends l'idée de la citation d'ouverture (« {cit['citation']} », {cit['auteur']}) pour la retourner "
                                   "contre la situation, " if cit else "")
                + "une image finale forte et alarmiste, puis la phrase-choc du live. Ensuite un appel court et naturel : s'abonner, partager, "
                "dire en commentaire quelle affaire inquiète le plus"
                + (f", puis termine EXACTEMENT par la signature : « {ch['signature']} » suivie d'une dernière punchline d'une ligne."
                   if ch.get("signature") else ", puis une dernière punchline d'une ligne.")
                + " Aucun fait nouveau, aucune source citée.")
    return ""


# ------------------------------------------------------------------ anti-répétition
_SENT = re.compile(r"(?<=[.!?…])\s+")
_MARK = re.compile(r"\[F\d+\]")
_STOP = set("le la les de des du un une et a à au aux en dans pour sur par que qui quoi ce cet cette ces il elle ils elles on nous vous "
            "est sont pas ne plus se sa son ses leur leurs y d l s n qu c j m t the of and to in is are a an que "
            "il lo gli della di da che non per con una e un "
            "في من علي الي عن مع هذا هذه ذلك تلك التي الذي ان او لا ما هو هي كل قد لم لن ثم بل كان كانت و ف ب ل ال".split())


def _key(s):
    return " ".join(_norm(_MARK.sub("", s)).split())


def deja_dit(secs, n=25):
    """Phrases d'humour / formules sans fait déjà employées (à ne pas réutiliser) : on les montre au rédacteur."""
    out = []
    for s in secs:
        for sent in _SENT.split(s.get("text") or ""):
            if not _MARK.search(sent) and 2 <= len(sent.split()) <= 18:
                out.append(" ".join(sent.split()))
    return out[-n:]


def anti_repetition(secs, locked=(), protect=()):
    """Supprime les phrases SANS FAIT qui répètent une phrase déjà dite, une formule (5 mots consécutifs) ou une vanne déjà
    employée. Jamais touchées : les phrases porteuses de faits, la citation, l'accueil et la signature de la chaîne (protect)."""
    keep_always = {_key(x) for p in protect if p for x in _SENT.split(p) if x.strip()}
    seen_sent, seen_gram, openers, punch, removed = set(), set(), {}, [], 0
    longues = []            # phrases longues déjà dites (même avec faits) : un quasi-doublon (≥ 80 % de mots communs) est retiré
    for s in secs:
        paras = re.split(r"\n\s*\n", s.get("text") or "")
        newp = []
        for para in paras:
            keep = []
            for sent in _SENT.split(para.strip()):
                if not sent:
                    continue
                k = _key(sent)
                toks = k.split()
                grams = {" ".join(toks[i:i + 5]) for i in range(len(toks) - 4)}
                grams = {g for g in grams if len(set(g.split()) - _STOP) >= 2}
                opener = " ".join(toks[:3]) if len(toks) >= 4 else ""
                court = len(toks) <= 14          # seules les phrases courtes sans fait (punchlines, tics) sont concernées
                mots = set(toks) - _STOP
                tic = len(toks) <= 10 and any(len(mots & x) >= 2 for x in punch)     # même vanne recyclée (« vraiment, chapeau »)
                dup = (k and k in seen_sent and len(toks) >= 2) or (court and (bool(grams & seen_gram) or tic
                                                                            or (opener and openers.get(opener, 0) >= 2)))
                if dup and not _MARK.search(sent) and s.get("kind") not in locked and k not in keep_always:
                    removed += 1
                    continue
                if len(toks) >= 8 and k not in keep_always:
                    st = set(toks)
                    # quasi-doublon : 80 % des mots de la plus courte des deux phrases déjà dits ensemble (la conclusion
                    # et le hook peuvent rappeler un fait : seuls les actes et « je relie les points » sont nettoyés)
                    if s.get("kind") in ("chapter", "liens") and any(len(st & x) / min(len(st), len(x)) >= 0.8 for x in longues):
                        removed += 1
                        continue
                    longues.append(st)
                seen_sent.add(k)
                seen_gram |= grams
                if opener and not _MARK.search(sent):
                    openers[opener] = openers.get(opener, 0) + 1
                if len(toks) <= 10 and not _MARK.search(sent) and len(mots) >= 2:
                    punch.append(mots)
                keep.append(sent)
            if keep:
                newp.append(" ".join(keep))
        if s.get("kind") not in locked:
            s["text"] = "\n\n".join(newp)
    if removed:
        print(f"   anti-répétition : {removed} formule(s) déjà dite(s) supprimée(s)")
    return removed
