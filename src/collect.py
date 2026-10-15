"""Collecte multi-sources : presse, agences, GDELT, YouTube, X, Reddit, HN, recherche Google."""
from __future__ import annotations

import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime

import requests

from . import config, llm


@dataclass
class Source:
    id: str = ""
    kind: str = ""          # presse | gdelt | web | youtube | x | reddit | hn
    title: str = ""
    url: str = ""
    publisher: str = ""
    date: str = ""
    text: str = ""
    meta: dict = field(default_factory=dict)


def _get(url, **kw):
    kw.setdefault("timeout", 15)
    headers = {"User-Agent": config.UA}
    headers.update(kw.pop("headers", {}))
    try:
        return requests.get(url, headers=headers, **kw)
    except Exception:
        return None


def _run(jobs, workers=8):
    """jobs = [(fn, args...)] -> liste aplatie des résultats, erreurs ignorées."""
    out = []
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(j[0], *j[1:]) for j in jobs]
        for f in futs:
            try:
                out += f.result() or []
            except Exception as e:
                print(f"  ! collecte: {str(e)[:100]}")
    return out


# ---------------------------------------------------------------- Google News
def google_news(query, hl, gl, limit=8, fiab=None):
    url = (f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}"
           f"&hl={hl}&gl={gl}&ceid={gl}:{hl}")
    r = _get(url)
    if not r or r.status_code != 200:
        return []
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return []
    out = []
    for it in root.findall(".//item")[:limit]:
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        publisher = src.text.strip() if src is not None and src.text else ""
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3]
        try:
            date = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
        except Exception:
            date = ""
        meta = {"edition": f"{hl}-{gl}"}
        if fiab:
            meta["fiab"] = fiab
        out.append(Source(kind="presse", title=title, url=(it.findtext("link") or "").strip(),
                          publisher=publisher, date=date, meta=meta))
    return out


def press_sweep(sujet):
    jobs = []
    for d in config.TOP_PRESS:
        hl, gl = ("fr", "FR") if d.endswith(".fr") else ("en", "US")
        jobs.append((google_news, f"{sujet} site:{d}", hl, gl, 3, "haute"))
    return _run(jobs, workers=8)


# ---------------------------------------------------------------- GDELT
def gdelt(query, limit=40):
    words = [w for w in re.findall(r"\w+", query) if len(w) > 2]
    if not words:
        return []
    params = {"query": " ".join(words), "mode": "artlist", "maxrecords": limit,
              "format": "json", "sort": "hybridrel"}
    for _ in range(3):
        r = _get("https://api.gdeltproject.org/api/v2/doc/doc", params=params, timeout=25)
        if r is not None and r.status_code == 200:
            try:
                arts = r.json().get("articles", [])
            except Exception:
                return []
            out = []
            for a in arts:
                d = a.get("seendate", "")
                date = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else ""
                out.append(Source(kind="gdelt", title=a.get("title", ""), url=a.get("url", ""),
                                  publisher=a.get("domain", ""), date=date,
                                  meta={"pays": a.get("sourcecountry"), "langue": a.get("language")}))
            return out
        time.sleep(6)  # GDELT : 1 requête / 5 s
    return []


# ---------------------------------------------------------------- YouTube
def youtube(query, hl, n=8):
    key = os.getenv("YT_API_KEY")
    if not key:
        return []
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", developerKey=key, cache_discovery=False)
    ids = []
    for order in ("relevance", "viewCount"):
        r = yt.search().list(q=query, part="id", maxResults=n, order=order,
                             type="video", relevanceLanguage=hl).execute()
        ids += [i["id"]["videoId"] for i in r.get("items", [])]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    res = yt.videos().list(id=",".join(ids[:50]), part="snippet,statistics").execute()
    out = []
    for it in res.get("items", []):
        sn, st = it["snippet"], it.get("statistics", {})
        out.append(Source(
            kind="youtube", title=sn["title"], publisher=sn["channelTitle"],
            url=f"https://www.youtube.com/watch?v={it['id']}", date=sn["publishedAt"][:10],
            text=f"{sn['title']}. {sn.get('description', '')[:600]}",
            meta={"vues": int(st.get("viewCount", 0)), "video_id": it["id"], "fiab": "faible"}))
    return out


def transcript(video_id, langs):
    try:
        from youtube_transcript_api import YouTubeTranscriptApi as Y
        if hasattr(Y, "get_transcript"):
            return " ".join(p["text"] for p in Y.get_transcript(video_id, languages=langs))
        return " ".join(s.text for s in Y().fetch(video_id, languages=langs))
    except Exception:
        return ""


# ---------------------------------------------------------------- X / Reddit / HN
def x_posts(query, n=20):
    tok = os.getenv("X_BEARER_TOKEN")
    if not tok:
        return []
    r = _get("https://api.x.com/2/tweets/search/recent",
             params={"query": f"{query} -is:retweet", "max_results": max(10, min(n, 100)),
                     "tweet.fields": "created_at,public_metrics", "expansions": "author_id",
                     "user.fields": "username"},
             headers={"Authorization": f"Bearer {tok}"})
    if not r or r.status_code != 200:
        print(f"  ! X API: {getattr(r, 'status_code', 'erreur')} (plan payant requis)")
        return []
    j = r.json()
    users = {u["id"]: u["username"] for u in j.get("includes", {}).get("users", [])}
    out = []
    for t in j.get("data", []):
        u = users.get(t.get("author_id"), "i")
        out.append(Source(kind="x", title=t["text"][:120], text=t["text"], publisher=f"@{u}",
                          url=f"https://x.com/{u}/status/{t['id']}",
                          date=t.get("created_at", "")[:10],
                          meta={**t.get("public_metrics", {}), "fiab": "faible"}))
    return out


def reddit(query, n=10):
    r = _get("https://www.reddit.com/search.json",
             params={"q": query, "sort": "top", "t": "year", "limit": n})
    if not r or r.status_code != 200:
        return []
    out = []
    for c in r.json().get("data", {}).get("children", []):
        d = c["data"]
        out.append(Source(kind="reddit", title=d["title"], publisher=f"r/{d['subreddit']}",
                          url="https://www.reddit.com" + d["permalink"],
                          text=f"{d['title']}. {d.get('selftext', '')[:800]}",
                          date=time.strftime("%Y-%m-%d", time.gmtime(d["created_utc"])),
                          meta={"score": d.get("score"), "fiab": "faible"}))
    return out


def hackernews(query, n=10):
    r = _get("https://hn.algolia.com/api/v1/search", params={"query": query, "tags": "story", "hitsPerPage": n})
    if not r or r.status_code != 200:
        return []
    return [Source(kind="hn", title=h.get("title") or "", publisher="Hacker News",
                   url=h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
                   date=(h.get("created_at") or "")[:10], meta={"fiab": "faible"})
            for h in r.json().get("hits", []) if h.get("title")]


# ---------------------------------------------------------------- Recherche Google (grounding Gemini)
def grounded(query):
    """Fait une vraie recherche Google via Gemini et récupère les URL citées."""
    prompt = (f"Recherche sur le web : {query}\n"
              "Donne les faits chiffrés, dates, noms, décisions et déclarations les plus solides, "
              "en citant les sites sources.")
    r = llm.ask(prompt, temperature=0.2, search=True, fatal=False)
    out = []
    try:
        for c in r.candidates[0].grounding_metadata.grounding_chunks or []:
            if c.web and c.web.uri:
                out.append(Source(kind="web", title=c.web.title or "", url=c.web.uri,
                                  publisher=c.web.title or "", meta={"requete": query}))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- Requêtes
def expand_queries(sujet, these, lang_nom, avoid=(), n=None):
    n = n or config.N_QUERIES
    p = (f"Sujet : {sujet}\nThèse / angle : {these or '(aucune)'}\n\n"
         f"Génère {n} requêtes de recherche web courtes (2 à 7 mots), en {lang_nom} "
         "(dont 2 en anglais), pour trouver : chiffres officiels, dates, décisions de justice, "
         "rapports, déclarations exactes, affaires, réactions sur X et forums, couverture "
         "internationale, contradictions et promesses non tenues. "
         f"Évite ces requêtes déjà faites : {list(avoid)[:20]}.\n"
         "Réponds en JSON : une liste de chaînes.")
    j = llm.ask_json(p, temperature=0.6)
    qs = [q for q in (j or []) if isinstance(q, str)]
    return qs[:n] or [sujet]


def collect_all(sujet, queries, lang, deep=False):
    hl, gl = lang["hl"], lang["gl"]
    editions = [(hl, gl)] + [e for e in config.EDITIONS if e != (hl, gl)]
    jobs = []
    if not deep:
        jobs += [(google_news, sujet, h, g, 10) for h, g in editions]
        jobs.append((press_sweep, sujet))
        jobs += [(youtube, sujet, hl), (x_posts, sujet), (reddit, sujet), (hackernews, sujet)]
    for i, q in enumerate(queries):
        jobs.append((google_news, q, hl, gl, 6))
        if i < config.GROUNDED_MAX:
            jobs.append((grounded, q))
    jobs += [(youtube, q, hl) for q in queries[:2]]
    out = _run(jobs, workers=6)
    # GDELT séquentiel (limite de débit)
    for q in [sujet] + queries[:2]:
        out += gdelt(q)
        time.sleep(5)
    return out


# ---------------------------------------------------------------- Nettoyage
def _norm_title(t):
    return re.sub(r"\W+", " ", t.lower()).strip()[:70]


def dedupe(sources, known=()):
    seen_u, seen_t, out = set(known), set(), []
    for s in sources:
        u = s.url.split("#")[0]
        t = _norm_title(s.title)
        if not u or u in seen_u or (t and t in seen_t):
            continue
        seen_u.add(u)
        if t:
            seen_t.add(t)
        out.append(s)
    return out


def assign_ids(sources, start=1):
    for i, s in enumerate(sources, start):
        s.id = f"S{i}"
    return start + len(sources)


def resolve_gnews(url):
    if "news.google.com" not in url:
        return url
    try:
        from googlenewsdecoder import gnewsdecoder
        d = gnewsdecoder(url, interval=0.3)
        if d.get("status"):
            return d["decoded_url"]
    except Exception:
        pass
    return url


def reliability(s):
    host = urllib.parse.urlparse(s.url).netloc.lower()
    if s.kind in ("youtube", "x", "reddit", "hn"):
        return "faible"
    if any(host.endswith(d) for d in config.OFFICIAL_SUFFIX):
        return "haute"
    if any(host.endswith(d) or host.endswith("." + d) for d in config.TOP_PRESS):
        return "haute"
    return "moyenne"


def _fetch(s, max_chars):
    if s.kind in ("youtube", "x", "reddit"):
        return
    s.url = resolve_gnews(s.url)
    r = _get(s.url, allow_redirects=True, timeout=20)
    if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
        return
    s.url = r.url
    try:
        import trafilatura
        t = trafilatura.extract(r.text, include_comments=False, include_tables=True, favor_recall=True)
    except Exception:
        t = None
    if t:
        s.text = t[:max_chars]


def enrich(sources, lang, max_fetch=45, max_chars=7000):
    """Récupère le texte intégral des meilleurs articles + transcriptions YouTube."""
    prio = {"presse": 3, "web": 3, "gdelt": 2, "hn": 1, "reddit": 1}
    cand = [s for s in sources if s.kind in prio and not s.text]
    cand.sort(key=lambda s: (-(s.meta.get("fiab") == "haute"), -prio[s.kind]))
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(lambda s: _fetch(s, max_chars), cand[:max_fetch]))
    vids = sorted([s for s in sources if s.kind == "youtube"],
                  key=lambda s: -s.meta.get("vues", 0))[:3]
    for s in vids:
        t = transcript(s.meta.get("video_id", ""), [lang["code"], "en"])
        if t:
            s.text = (s.text + " " + t)[:max_chars]
    for s in sources:
        s.meta.setdefault("fiab", reliability(s))
        if not s.text:
            s.text = s.title
    return sources
