"""MODE « COMMENTAIRE D'UNE VIDÉO » : ton script pour commenter une vidéo (déposée dans Drive montage-joints).

Étapes :
  1. la vidéo est TRANSCRITE (Groq gratuit, sinon transcription locale) — lecture seule, rien n'est supprimé ni déplacé ;
  2. l'IA choisit l'OUVERTURE CHOC (le passage le plus fort) et les PASSAGES à faire écouter, dans l'ordre de la vidéo ;
     chaque passage est VÉRIFIÉ ici, sans IA : il existe mot pour mot dans la transcription, dure 8 à 25 s, finit sur
     une fin de phrase, ne chevauche aucun autre ;
  3. l'IA écrit, pour chaque passage, ton ANNONCE (ce qui va passer) et ta RÉACTION ; la CITATION entre les deux est
     recopiée de la transcription (jamais réécrite) ;
  4. sorties : script_teleprompter.txt (avec « 🎬 ÉCOUTEZ ÇA » à chaque passage), script_annote.md, et passages.json que
     le Montage utilise : le n-ième « écoutez ça » que tu dis = le n-ième passage. Autant de « écoutez ça » dans le
     script que de passages : contrôlé avant d'écrire les fichiers."""
from __future__ import annotations

import json
import os
import re
import unicodedata
import subprocess
import tempfile
import time

from . import config, hors_contexte, llm, structure

# mot déclencheur à dire (et que le Montage écoute), par langue
# ⚠ EXACTEMENT les annonces que le Montage reconnaît (Montage-LV-final, montage/keywords.py, testé là-bas) :
# une autre formule = la vidéo commentée ne repartirait jamais
DECLENCHEUR = {"fr": "écoutez ça", "en": "listen to this", "it": "ascoltate questo", "es": "escuchen esto",
               "de": "hört euch das an", "pt": "ouçam isto", "ar": "اسمعوا هذا"}
P_MIN, P_MAX = 8.0, 25.0
ENDS = re.compile(r"[.!?؟…][\"»”]?$")
CONNECT = r"(?i)^(et|mais|donc|alors|du coup|parce que|and|but|so|e|ma|quindi|y|pero|و|ثم|لكن)\b"


# ------------------------------------------------------------------ transcription
def _keys(*names):
    out = []
    for n in names:
        for k in re.split(r"[,\s]+", os.getenv(n, "") or ""):
            if k.strip() and k.strip() not in out:
                out.append(k.strip())
    return out


def _groq(audio_dir, parts, lang_hint):
    import requests
    keys = _keys("GROQ_API_KEYS", "GROQ_API_KEY", "GROQ_API_KEYS_PLUS")
    if not keys:
        raise RuntimeError("aucune clé Groq")
    words, lang = [], None
    for k, (path, off) in enumerate(parts):
        for attempt in range(6):
            key = keys[(k + attempt) % len(keys)]
            with open(path, "rb") as fh:
                data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json",
                        "timestamp_granularities[]": ["word", "segment"]}
                if lang_hint and lang_hint != "auto":
                    data["language"] = lang_hint
                r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                  headers={"Authorization": f"Bearer {key}"}, files={"file": fh}, data=data, timeout=300)
            if r.status_code == 200:
                j = r.json()
                lang = lang or j.get("language")
                for w in j.get("words") or []:
                    words.append({"w": str(w["word"]).strip(), "t0": round(w["start"] + off, 3), "t1": round(w["end"] + off, 3)})
                break
            if r.status_code in (429, 500, 502, 503):
                time.sleep(min(60, 8 * (attempt + 1)))
                continue
            raise RuntimeError(f"Groq {r.status_code} : {r.text[:160]}")
        else:
            raise RuntimeError("Groq : quota épuisé")
    return words, lang


def _local(video, lang_hint):
    from faster_whisper import WhisperModel
    m = WhisperModel("small", device="cpu", compute_type="int8")
    segs, info = m.transcribe(video, language=None if lang_hint in ("", "auto") else lang_hint, word_timestamps=True,
                              vad_filter=True)
    words = [{"w": w.word.strip(), "t0": round(w.start, 3), "t1": round(w.end, 3)} for s in segs for w in (s.words or [])]
    return words, info.language


def transcrire(video: str, lang_hint: str = "auto") -> tuple[list, str]:
    """Mots horodatés de la vidéo + langue. Groq (gratuit, rapide) par morceaux de 10 min, sinon transcription locale."""
    tmp = tempfile.mkdtemp()
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                               capture_output=True, text=True).stdout.strip() or 0)
    parts, step = [], 600.0
    t = 0.0
    while t < dur - 0.5:
        p = os.path.join(tmp, f"p{len(parts):03d}.mp3")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-t", f"{step:.2f}", "-i", video, "-vn", "-ac", "1",
                        "-ar", "16000", "-b:a", "32k", p], check=True)
        parts.append((p, t))
        t += step
    try:
        words, lang = _groq(tmp, parts, lang_hint)
        print(f"   transcription Groq : {len(words)} mots")
    except Exception as e:  # noqa: BLE001
        print(f"   ! Groq indisponible ({str(e)[:120]}) : transcription locale (plus lente)")
        words, lang = _local(video, lang_hint)
        print(f"   transcription locale : {len(words)} mots")
    code = (lang or "").lower()[:2]
    code = {"fr": "fr", "en": "en", "it": "it", "es": "es", "de": "de", "pt": "pt", "ar": "ar"}.get(code) or \
        {"french": "fr", "english": "en", "italian": "it", "spanish": "es", "german": "de", "portuguese": "pt",
         "arabic": "ar"}.get((lang or "").lower(), "fr")
    return words, code


def phrases(words: list) -> list:
    out, cur = [], []

    def flush():
        if cur:
            out.append({"i": len(out), "t0": cur[0]["t0"], "t1": cur[-1]["t1"],
                        "text": re.sub(r"\s+([,.;:!?؟،])", r"\1", " ".join(w["w"] for w in cur))})
            cur.clear()
    for w in words:
        if cur and (w["t0"] - cur[-1]["t1"] > 1.0 or w["t1"] - cur[0]["t0"] > 14):
            flush()
        cur.append(w)
        if ENDS.search(w["w"]) and len(cur) >= 3:
            flush()
    flush()
    return out


# ------------------------------------------------------------------ choix des passages (IA proposée, code qui vérifie)
def _fmt(s):
    return f"{int(s // 60)}:{int(s % 60):02d}"


def choisir(S: list, lang: dict, n_voulu: int, these: str = "") -> tuple[dict | None, list]:
    """(ouverture, passages dans l'ordre de la vidéo) — tous vérifiés."""
    lignes = "\n".join(f"[{s['i']}] {_fmt(s['t0'])} ({max(1, round(s['t1'] - s['t0']))}s) {s['text'][:300]}" for s in S)
    prompt = f"""Tu prépares une vidéo YouTube où un commentateur RÉAGIT à une vidéo. Le commentateur parle {lang['nom']} ;
la vidéo commentée peut être dans une autre langue (code détecté : {lang.get('video', '?')}) : les TITRES sont écrits en
{lang['nom']}, quelle que soit la langue de la vidéo.
Voici la transcription de la vidéo commentée, en phrases numérotées : [numéro] horaire (durée) texte.

1. OUVERTURE : le passage LE PLUS CHOQUANT / controversé / fort de toute la vidéo (il ouvrira la vidéo, avant tout).
2. PASSAGES : {n_voulu} passages à faire écouter, DANS L'ORDRE DE LA VIDÉO, qui portent les idées clés, les déclarations
   fortes, les contradictions, les chiffres, ce qui fait réagir. Chaque passage : phrases CONSÉCUTIVES, de {P_MIN:.0f} à
   {P_MAX:.0f} secondes au total (additionne les durées), compréhensible seul, qui commence au début d'une phrase et finit à
   la fin d'une phrase. Les passages ne se chevauchent pas. Aucun passage ne reprend l'ouverture (déjà entendue).
3. Pour chaque passage : un titre court (3 à 7 mots) qui annonce ce qui va suivre, fidèle à ce qui est dit.
{('Angle du commentateur : ' + these) if these else ''}
start / end = NUMÉROS des phrases entre crochets (pas des horaires).
Réponds UNIQUEMENT en JSON : {{"ouverture": {{"start": n, "end": n, "titre": "..."}},
"passages": [{{"start": n, "end": n, "titre": "..."}}]}}

TRANSCRIPTION :
{lignes}"""
    j = llm.ask_json(prompt, temperature=0.3) or {}
    rejets: list = []

    def idx(v, fin=False):
        """Numéro de phrase. Tolère une réponse en horaire (« 1:27 », 87.5) : la phrase qui contient cet instant."""
        if isinstance(v, str) and ":" in v:
            mm, _, ss = v.strip().rpartition(":")
            t = float(mm or 0) * 60 + float(ss)
        elif isinstance(v, float) and not v.is_integer():
            t = v
        else:
            return int(str(v).strip().strip("[]"))
        k = min(range(len(S)), key=lambda i: 0 if S[i]["t0"] <= t <= S[i]["t1"] else
                min(abs(S[i]["t0"] - t), abs(S[i]["t1"] - t)))
        return k

    def ok(x):
        try:
            a, b = idx(x["start"]), idx(x["end"], True)
        except (KeyError, TypeError, ValueError):
            rejets.append(f"illisible {str(x)[:60]}")
            return None
        if a > b:
            a, b = b, a
        if not (0 <= a < len(S) and 0 <= b < len(S)):
            rejets.append(f"hors transcription [{a}-{b}]")
            return None
        # jamais un passage qui commence par « Et / Mais / Donc… » (il dépend de la phrase d'avant) : on saute ce début
        while a < b and re.match(CONNECT, S[a]["text"]) and S[b]["t1"] - S[a + 1]["t0"] >= P_MIN:
            a += 1
        # trop court pour sauter ce début : on prend la phrase d'avant (le contexte), sinon le passage est refusé
        for _ in range(2):
            if not re.match(CONNECT, S[a]["text"]) or a == 0 or S[b]["t1"] - S[a - 1]["t0"] > P_MAX:
                break
            a -= 1
        if re.match(CONNECT, S[a]["text"]):
            rejets.append(f"[{a}] commence par « {S[a]['text'][:12]}… »")
            return None
        while b > a and S[b]["t1"] - S[a]["t0"] > P_MAX:          # trop long : on finit plus tôt
            b -= 1
        while S[b]["t1"] - S[a]["t0"] < P_MIN and b + 1 < len(S) and S[b + 1]["t1"] - S[a]["t0"] <= P_MAX:   # trop court
            b += 1
        d = S[b]["t1"] - S[a]["t0"]
        if d < P_MIN - 1.5 or d > P_MAX + 0.5:
            rejets.append(f"[{a}-{b}] {d:.0f} s")
            return None
        return {"a": a, "b": b, "start": round(S[a]["t0"], 3), "end": round(S[b]["t1"], 3),
                "titre": " ".join(str(x.get("titre") or "").split())[:70],
                "citation": " ".join(s["text"] for s in S[a:b + 1])}
    ouv = ok(j.get("ouverture") or {})
    ps = []

    def prendre(lst):
        for x in lst or []:
            p = ok(x)
            # jamais deux fois la même chose : un passage ne reprend pas l'ouverture choc (déjà entendue au début)
            if p and not any(min(p["end"], q["end"]) - max(p["start"], q["start"]) > 0
                             for q in ps + ([ouv] if ouv else [])):
                ps.append(p)
    prendre(j.get("passages"))
    # trop de passages refusés par la vérification (trop longs, coupés, chevauchement…) : on en redemande d'AUTRES
    for _ in range(2):
        if len(ps) >= max(2, n_voulu - 1):
            break
        pris = ", ".join(f"[{q['a']}-{q['b']}]" for q in sorted(ps + ([ouv] if ouv else []), key=lambda q: q["a"]))
        print(f"   {len(ps)}/{n_voulu} passage(s) valable(s) (refusés : {'; '.join(rejets[-6:]) or 'chevauchement'}) :"
              " l'IA en propose d'autres")
        j2 = llm.ask_json(prompt + f"""

DÉJÀ PRIS (n'en reprends AUCUNE phrase) : {pris or 'rien'}.
Donne {n_voulu - len(ps)} AUTRES passages (même règles : {P_MIN:.0f} à {P_MAX:.0f} s, phrases entières), même format JSON.""",
                          temperature=0.4) or {}
        prendre(j2.get("passages"))
    ps.sort(key=lambda p: p["start"])
    if not ps and ouv:   # vidéo très courte : tout tient dans l'ouverture → l'ouverture est jouée seule, sans reprise
        raise SystemExit("Vidéo commentée trop courte : aucun passage en plus de l'ouverture choc.")
    if not ps:
        raise SystemExit("Aucun passage exploitable dans la vidéo commentée (transcription vide ou IA indisponible).")
    if not ouv:
        ouv = dict(ps[0])
    return ouv, ps


# ------------------------------------------------------------------ écriture
def _cle(k) -> str:
    """« Réaction » → reaction, « Annonce » → annonce."""
    return unicodedata.normalize("NFKD", str(k)).encode("ascii", "ignore").decode().strip().lower()


# « le premier passage », « le 3e extrait », « ce deuxième segment », « le dernier extrait »… : jamais à l'oral
NUMEROTE = re.compile(r"\b(premi[eè]re?|deuxi[eè]me|second[e]?|troisi[eè]me|quatri[eè]me|cinqui[eè]me|sixi[eè]me|"
                      r"septi[eè]me|huiti[eè]me|neuvi[eè]me|dixi[eè]me|\d+\s*(?:e|è|ème|eme|er|re)|dernier|derni[eè]re)"
                      r"\s+(passage|segment|extrait|clip|moment|partie)s?\b", re.I)
def ecrire(lang: dict, style: str, these: str, ouv: dict, ps: list, mots_cible: int) -> dict:
    dec = DECLENCHEUR.get(lang["code"], DECLENCHEUR["fr"])
    per = min(220, max(40, int(mots_cible * 0.8 / max(1, len(ps)))))   # une réaction n'est jamais un monologue
    liste = "\n".join(f"[{k + 1}] « {p['citation'][:500]} »" for k, p in enumerate(ps))
    prompt = f"""Tu écris le texte de prompteur d'un commentateur YouTube qui RÉAGIT à une vidéo (langue : {lang['nom']}), dans le
style de sa chaîne : DU FEU — indignation, alerte, humour noir, ironie glaciale{(', satire mordante' if style == 'satirique' else ', regard d’expert qui démonte')} ;
jamais un texte tiède qui répète la version officielle. Le spectateur vient de voir l'ouverture choc : « {ouv['citation'][:500]} ».
Le script commence déjà par une citation célèbre (ajoutée automatiquement) : n'en écris pas d'autre.
{('Angle du commentateur : ' + these) if these else ''}
REGISTRE : chaque réaction suit FAIT ou PHRASE ENTENDUE -> ANALYSE (pourquoi c'est grave, à qui ça profite, quel précédent, quelle
contradiction) -> PUNCHLINE qui claque (humour noir ou alarme). Contre-lectures : ce que la version officielle oublie, les précédents
historiques avérés (ex. les « armes de destruction massive » en Irak) quand ils éclairent vraiment le sujet. Zéro phrase neutre.
Écris :
- "hook" : 3 à 6 phrases COURTES, ultra-choc, juste après la citation : ta réaction à chaud à l'ouverture, ce qui est révoltant ou
  inquiétant, et une boucle ouverte (« et ce n'est pas le pire… », « gardez ça en tête, ça revient à la fin ») ; aucune salutation ;
- "intro" : 80 à 150 mots, le DÉCOR : qui parle dans cette vidéo, dans quel contexte, l'histoire qui mène à ce moment, et pourquoi le
  spectateur doit s'en soucier ; termine par une question ouverte au public ;
- pour CHAQUE passage numéroté ci-dessous, dans l'ordre :
  - "annonce" : 20 à 50 mots, à l'oral, naturels, qui préparent le passage (qui parle, de quoi, ce qu'il faut guetter) et
    donnent envie de l'entendre ; NE cite PAS le passage ; n'écris JAMAIS « le premier passage / segment / extrait » ni
    aucun numéro ;
  - "titre" : 3 à 7 mots, le titre affiché à l'écran pendant que la vidéo attend ce passage : il dit EXACTEMENT ce que
    dit CE passage (rien d'autre), en {lang['nom']} ;
  - "traduction" : {('la traduction fidèle du passage en ' + lang['nom'] + ' (la vidéo est dans une autre langue)') if lang.get('video') not in (None, '?', lang['code']) else 'chaîne vide'} ;
  - "reaction" : environ {per} mots de réaction juste après l'avoir entendu (analyse, contradiction, ironie, chiffres,
    question au public) ; ne commence jamais par répéter la citation ;
- "conclusion" : 80 à 140 mots, le verdict qui découle de tout ce qui précède, une dernière punchline, puis une question OUVERTE au
  public (jamais « écrivez X si… », jamais « likez / partagez / abonnez-vous / dans les commentaires »).
N'invente aucun fait ; une accusation est présentée comme une opinion ou une question. N'écris JAMAIS les mots
« {dec} » toi-même (ils sont ajoutés automatiquement).
{hors_contexte.REGLE} (Ne s'applique pas à "traduction", qui reste fidèle.)
Réponds UNIQUEMENT en JSON : {{"hook": "...", "intro": "...", "blocs": [{{"n": 1, "titre": "...", "annonce": "...", "traduction": "...", "reaction": "..."}}], "conclusion": "..."}}

PASSAGES :
{liste}"""
    j = {}

    def normal(r):   # réponses tolérées : blocs en dict {"1": {...}}, clés accentuées (« réaction »), liste seule
        if isinstance(r, list):
            r = {"blocs": r}
        if not isinstance(r, dict):
            return {}
        r = {_cle(k): v for k, v in r.items()}
        bl = r.get("blocs") or r.get("passages") or r.get("blocks") or []
        if isinstance(bl, dict):
            bl = [dict(v, n=v.get("n") or k) if isinstance(v, dict) else v for k, v in bl.items()]
        r["blocs"] = [{_cle(k): v for k, v in b.items()} for b in bl if isinstance(b, dict)]
        return r

    def bons(r):     # blocs complets ET annonce naturelle (jamais « le premier passage », « le 3e extrait »…)
        return sum(1 for b in (r.get("blocs") or []) if isinstance(b, dict) and b.get("reaction")
                   and b.get("annonce") and not NUMEROTE.search(str(b["annonce"])))
    for essai in range(3):      # réponse incomplète ou annonces numérotées : nouvel essai, on garde la meilleure
        r = normal(llm.ask_json(prompt, temperature=0.6 if essai == 0 else 0.4))
        nb = bons(r)
        if (nb, bool(r.get("intro"))) > (bons(j), bool(j.get("intro"))):
            j = r
        if nb == 0:
            print(f"   ? réponse reçue : clés {sorted(r)[:8]}, blocs {len(r.get('blocs') or [])}"
                  + (f", 1er bloc {sorted(r['blocs'][0])[:6]}" if r.get("blocs") else ""))
        if nb >= len(ps) and r.get("intro"):
            break
        print(f"   ! réponse incomplète ou annonces numérotées ({nb}/{len(ps)} bons blocs) : nouvel essai" if essai < 2
              else f"   ! {len(ps) - nb} bloc(s) à revoir : à improviser (marqués dans le script)")
    def _n(b):
        try:
            return int(b.get("n") or 0)
        except (TypeError, ValueError):
            return 0
    blocs = {_n(b): b for b in (j.get("blocs") or []) if isinstance(b, dict)}
    pat = re.compile(re.escape(dec), re.I)
    clean = lambda t: pat.sub("", " ".join(str(t or "").split())).strip()     # noqa: E731
    for b in blocs.values():    # dernier filet : une annonce encore numérotée est remplacée par le titre du passage
        if NUMEROTE.search(str(b.get("annonce") or "")):
            b["annonce"] = ""
    return {"hook": sansQuemande(clean(j.get("hook"))), "intro": sansQuemande(clean(j.get("intro"))),
            "conclusion": sansQuemande(clean(j.get("conclusion"))),
            "blocs": [{"annonce": clean((blocs.get(k + 1) or {}).get("annonce")),
                       "traduction": clean((blocs.get(k + 1) or {}).get("traduction")),
                       "titre": clean((blocs.get(k + 1) or {}).get("titre"))[:70],
                       "reaction": clean((blocs.get(k + 1) or {}).get("reaction"))} for k in range(len(ps))]}


# jamais d'appel « likez / partagez / abonnez-vous », « écrivez X si… », « dans les commentaires » (règle de la chaîne) :
# la phrase qui le porte est retirée
QUEMANDE = re.compile(r"(?i)\b(lik(ez|e)|partag(ez|e)|abonn(ez|e)|abonnement|cloche|commentaires?|écrivez|ecrivez|subscribe|"
                      r"like and|share th|comment below|iscriv|condivid|اشترك|تعليق)")
def sansQuemande(t: str) -> str:
    return " ".join(p for p in re.split(r"(?<=[.!?…؟])\s+", str(t or "")) if p and not QUEMANDE.search(p)).strip()


def run(a, video: str, video_nom: str, out_root: str) -> str:
    """Point d'entrée : écrit les fichiers dans prompter/<date>_commentaire-<vidéo>/ et renvoie ce dossier."""
    t0 = time.time()
    print(f"[1/4] Vidéo commentée : {video_nom}")
    # la vidéo commentée peut être en anglais, en arabe… : sa langue est DÉTECTÉE (jamais forcée) ; ton script, lui,
    # est dans TA langue (choix « langue », auto = français) — passages écoutés en VO, sous-titrés par le Montage
    words, code = transcrire(video, "auto")
    if len(words) < 30:
        raise SystemExit("Transcription de la vidéo commentée vide ou presque : vidéo sans parole ?")
    if (a.langue or "auto").lower() == "auto":
        a.langue = "fr"
    lang = dict(config.lang_cfg(a.langue, ""))
    lang["video"] = (code or "?")[:2].lower()
    S = phrases(words)
    dur_v = words[-1]["t1"]
    print(f"   {len(S)} phrases, {_fmt(dur_v)}, vidéo en « {lang['video']} » → ton script en {lang['nom']}")
    mots = round(a.duree * a.wpm)
    n = max(4, min(14, round(a.duree / 2)))           # ≈ un passage toutes les 2 min de ton commentaire
    print(f"[2/4] Choix de l'ouverture et de {n} passages…")
    ouv, ps = choisir(S, lang, n, a.these)
    print(f"   ouverture {_fmt(ouv['start'])} ({ouv['end'] - ouv['start']:.0f} s) — {len(ps)} passage(s) vérifié(s)")
    print("[3/4] Écriture de tes annonces et réactions…")
    tx = ecrire(lang, a.style, a.these, ouv, ps, mots)
    reste = 0                           # tes phrases : jamais « nous / notre / nos » (la traduction, elle, reste fidèle)
    for o, k in [(tx, "hook"), (tx, "intro"), (tx, "conclusion")] + [(bl, x) for bl in tx["blocs"] for x in ("annonce", "reaction")]:
        if o.get(k):
            o[k], r = hors_contexte.corriger(o[k], lang["code"], llm.ask_json)
            reste += r
    if reste:
        print(f"   ! {reste} « nous / notre / nos » restant(s) dans tes phrases (réécriture IA refusée) — relis-les")
    for p, b in zip(ps, tx["blocs"]):   # titre réécrit d'après le passage FINAL (bornes vérifiées) : toujours fidèle
        if b.get("titre"):
            p["titre"] = b["titre"]
    dec = DECLENCHEUR.get(lang["code"], DECLENCHEUR["fr"])
    DEC = dec.upper()
    # --- citation célèbre d'ouverture (réelle, vérifiée, sinon liste sûre), comme les lives ; puis hook de feu, accueil de
    # la chaîne, décor, passages, verdict et signature
    ctx = {"sujet": f"{os.path.splitext(video_nom)[0]} — {ouv.get('titre', '')}", "these": a.these or "", "lang": lang,
           "points": [{"intitule": p["titre"]} for p in ps]}
    try:
        cit = structure.citation(ctx)
    except Exception as e:
        print(f"   ! citation d'ouverture impossible ({str(e)[:60]})")
        cit = None
    ch = structure.chaine(lang["code"])
    tete = [structure.citation_text(cit, lang["code"]) if cit else "", tx.get("hook") or "", ch.get("accueil", "")]
    # --- texte du prompteur
    L = [x for t in tete if t for x in (t, "")] + [tx["intro"] or "", ""]
    ann = [f"# Commentaire : {video_nom}", "", f"**OUVERTURE CHOC** ({_fmt(ouv['start'])}) : « {ouv['citation']} »", "",
           "## Citation, hook, accueil", "", *[t for t in tete if t], "", "## Décor", "", tx["intro"], ""]
    for k, (p, b) in enumerate(zip(ps, tx["blocs"])):
        L += [b["annonce"] or f"{p['titre']}.", "", f"🎬 {DEC} !", "", (f"[ ne pas lire — on entend (VO) : « {p['citation'][:220]} » — en clair : « {b['traduction'][:260]} » ]"
                 if b.get("traduction") else f"[ ne pas lire — on entend : « {p['citation'][:220]} » ]"), "",
              b["reaction"] or "[ ta réaction, librement ]", ""]
        ann += [f"## {k + 1}. {p['titre']}  ({_fmt(p['start'])} → {_fmt(p['end'])}, {p['end'] - p['start']:.0f} s)", "",
                b["annonce"], "", f"> 🎬 **{DEC} !** — « {p['citation']} »" + (f"\n>\n> *{b['traduction']}*" if b.get("traduction") else ""), "", b["reaction"], ""]
    L += [tx["conclusion"] or ""] + (["", ch["signature"]] if ch.get("signature") else [])
    ann += ["## Conclusion", "", tx["conclusion"]] + ([ "", ch["signature"]] if ch.get("signature") else [])
    txt = "\n".join(L).strip() + "\n"
    # --- contrôle : exactement un « écoutez ça » par passage (le Montage s'y fie)
    n_dec = len(re.findall(re.escape(DEC), txt))
    if n_dec != len(ps):
        raise SystemExit(f"Contrôle : {n_dec} « {dec} » dans le script pour {len(ps)} passages — script refusé.")
    nom = re.sub(r"[^\w-]+", "-", os.path.splitext(video_nom)[0])[:40].strip("-") or "video"
    d = os.path.join(out_root, time.strftime("%Y-%m-%d_%Hh%M") + f"_commentaire-{nom}")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "script_teleprompter.txt"), "w", encoding="utf-8").write(txt)
    open(os.path.join(d, "script_annote.md"), "w", encoding="utf-8").write("\n".join(ann) + "\n")
    data = {"version": 1, "video": video_nom, "langue": lang["code"], "declencheur": dec,
            "ouverture": {k: ouv[k] for k in ("start", "end", "titre", "citation")},
            "passages": [{"n": k + 1, **{x: p[x] for x in ("start", "end", "titre", "citation")},
                          "annonce": tx["blocs"][k]["annonce"]} for k, p in enumerate(ps)],
            "transcription": words}
    json.dump(data, open(os.path.join(d, "passages.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"mode": "commentaire", "video": video_nom, "duree": a.duree, "langue": lang["code"]},
              open(os.path.join(d, "requete.json"), "w", encoding="utf-8"), ensure_ascii=False)
    est = len(txt.split()) / a.wpm
    msg = (f"**Commentaire de « {video_nom} »**\n\nScript : {len(txt.split())} mots ≈ {est:.1f} min de parole "
           f"+ {sum(p['end'] - p['start'] for p in ps) / 60:.1f} min de passages · {len(ps)} « {dec} » · "
           f"ouverture choc à {_fmt(ouv['start'])} · {round(time.time() - t0)} s"
           + (f"\n\nIA utilisées : {llm.usage()}" if llm.usage() else ""))
    print("[4/4] " + msg.replace("**", ""))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(msg + "\n")
    return d
