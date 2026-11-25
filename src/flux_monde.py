"""Flux d'actualité HORS grands médias (catalogue du projet open source « World Monitor », koala73/worldmonitor) :
enquêtes, terrain des conflits, l'autre camp (cité comme tel), le monde vu de chez lui, déclarations directes.
Lus UNE fois par run (en parallèle), puis filtrés par les mots du sujet. Un flux mort ou bloqué est simplement ignoré :
cette source s'ajoute aux autres, elle ne remplace rien."""
from __future__ import annotations

import re
import threading
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

FLUX = [
    ('Al Jazeera', 'https://www.aljazeera.com/xml/rss/all.xml'),
    ('Middle East Eye', 'https://www.middleeasteye.net/rss'),
    ('Responsible Statecraft', 'https://responsiblestatecraft.org/feed/'),
    ('Consortium News', 'https://consortiumnews.com/feed/'),
    ('The Grayzone', 'https://thegrayzone.com/feed/'),
    ('The Intercept', 'https://theintercept.com/feed/?rss'),
    ('Mondafrique', 'https://mondafrique.com/feed/'),
    ('Les Crises', 'https://www.les-crises.fr/feed/'),
    ('Blast', 'https://www.blast-info.fr/feed'),
    ('Le Monde diplomatique', 'https://www.monde-diplomatique.fr/rss/'),
    ('Anadolu (FR)', 'https://www.aa.com.tr/fr/rss/default?cat=actualite'),
    ('Press TV (Iran)', 'https://www.presstv.ir/rss.xml'),
    ('TASS (Russie)', 'https://tass.com/rss/v2.xml'),
    ('Global Times (Chine)', 'https://www.globaltimes.cn/rss/outbrain.xml'),
    ('Haaretz', 'https://www.haaretz.com/srv/haaretz-latest-headlines'),
    ('Courrier international', 'https://www.courrierinternational.com/feed/all/rss.xml'),
    ('OCCRP (enquêtes corruption)', 'https://www.occrp.org/en/feed'),
    ('Lighthouse Reports', 'https://www.lighthousereports.com/feed/'),
    ('ProPublica', 'https://www.propublica.org/feeds/propublica/main'),
    ('Oryx (pertes militaires documentées)', 'https://www.oryxspioenkop.com/feeds/posts/default?alt=rss'),
    ('International Crisis Group', 'https://www.crisisgroup.org/rss'),
    ('War on the Rocks', 'https://warontherocks.com/feed/'),
    ('Sudan War Monitor', 'https://sudanwarmonitor.com/feed'),
    ('ONU Info (UN News)', 'https://news.un.org/feed/subscribe/en/news/all/rss.xml'),
    ('RAND', 'https://www.rand.org/pubs/articles.xml'),
    ('Stimson Center', 'https://www.stimson.org/feed/'),
    ('Atlantic Council', 'https://www.atlanticcouncil.org/feed/'),
    ('CSIS', 'https://www.csis.org/rss.xml'),
    ('Meduza (opposition russe)', 'https://meduza.io/rss/en/all'),
    ('Moscow Times', 'https://www.themoscowtimes.com/rss/news'),
    ('Novaya Gazeta Europe', 'https://novayagazeta.eu/feed/rss'),
    ("RT (média d'État russe)", 'https://rt-english.com/rss/russia/'),
    ('Kyiv Independent', 'https://kyivindependent.com/news-archive/rss/'),
    ('Eurasianet', 'https://eurasianet.org/rss'),
    ('LRT (Lituanie)', 'https://www.lrt.lt/en/news-in-english?rss'),
    ("IRNA (agence d'État iranienne)", 'https://en.irna.ir/rss'),
    ('Mehr News (Iran)', 'https://en.mehrnews.com/rss'),
    ('Syria Direct', 'https://syriadirect.org/feed/'),
    ('The Syrian Observer', 'https://syrianobserver.com/feed'),
    ('Naharnet (Liban)', 'https://www.naharnet.com/tags/lebanon/en/feed.atom'),
    ('Jerusalem Post', 'https://www.jpost.com/rss/rssfeedsheadlines.aspx'),
    ('The National (Émirats)', 'https://www.thenationalnews.com/arc/outboundfeeds/rss/?outputType=xml'),
    ('Gulf News', 'https://gulfnews.com/feed/'),
    ('Daily Sabah (Turquie)', 'https://www.dailysabah.com/rss/home-page'),
    ('Libya Herald', 'https://libyaherald.com/rss.xml'),
    ('Egypt Independent', 'https://www.egyptindependent.com/feed/'),
    ('Jeune Afrique', 'https://www.jeuneafrique.com/feed/'),
    ('Journal du Mali', 'https://journaldumali.com/feed/'),
    ('Sahelien.com', 'https://sahelien.com/feed/'),
    ('Le Sahel (Niger)', 'https://www.lesahel.org/feed/'),
    ('APS (Sénégal)', 'https://aps.sn/feed/'),
    ('La Presse de Tunisie', 'https://www.lapresse.tn/feed/'),
    ('Africanews', 'https://www.africanews.com/feed/'),
    ('Dawn (Pakistan)', 'https://www.dawn.com/feeds/home/'),
    ('The Hindu (Inde)', 'https://www.thehindu.com/feeder/default.rss'),
    ('Asahi Shimbun (Japon)', 'https://www.asahi.com/rss/asahi/newsheadlines.rdf'),
    ('Korea Herald', 'https://www.koreaherald.com/rss/newsAll'),
    ("Truth Social (Donald Trump)", "https://trumpstruth.org/feed"),
]

# quelques équivalences français → anglais (la plupart de ces flux sont en anglais)
ALIAS = {"pologne": "poland polish", "iran": "iranian tehran", "israel": "israeli", "russie": "russia russian moscow kremlin",
         "ukraine": "ukrainian kyiv", "etats": "us usa washington", "chine": "china chinese beijing", "yemen": "houthi houthis",
         "liban": "lebanon hezbollah", "syrie": "syria syrian", "gaza": "palestinian hamas", "arabie": "saudi riyadh",
         "allemagne": "germany german", "otan": "nato", "turquie": "turkey turkish", "inde": "india indian", "coree": "korea",
         "poutine": "putin", "netanyahou": "netanyahu", "egypte": "egypt", "irak": "iraq iraqi", "soudan": "sudan",
         "algerie": "algeria", "maroc": "morocco", "tunisie": "tunisia", "emirats": "uae emirates", "qatar": "qatari",
         "koweit": "kuwait", "oman": "omani", "bahrein": "bahrain", "europeenne": "eu europe", "nucleaire": "nuclear",
         "guerre": "war", "frappe": "strike strikes", "missile": "missiles", "sanctions": "sanctions", "petrole": "oil"}
VIDES = set("les des une dans pour par sur avec sans mais plus moins tout tous cette ces son ses leur leurs qui que quoi dont the and for with from that this have has are was were will been their about after over into says said new".split())

_lock = threading.Lock()
_cache = None


def _plat(s):
    return re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFD", str(s).lower()).encode("ascii", "ignore").decode())


def _txt(s):
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")
    for a, b in (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
        s = s.replace(a, b)
    s = re.sub(r"&#x([0-9a-f]+);", lambda m: chr(int(m.group(1), 16)), s, flags=re.I)
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"<[^>]+>", " ", s)                 # balises (y compris celles qui étaient encodées)
    return re.sub(r"\s+", " ", s).strip()


def _tag(x, t):
    m = re.search(rf"<{t}[^>]*>([\s\S]*?)</{t}>", x, re.I)
    return m.group(1) if m else ""


def _lire(nom, url, get):
    r = get(url, timeout=15)
    if r is None or r.status_code != 200:
        return []
    x = r.text
    items = re.split(r"<item[\s>]", x)[1:] or re.split(r"<entry[\s>]", x)[1:]
    out = []
    for it in items[:80]:
        titre = _txt(_tag(it, "title"))
        lien = _txt(_tag(it, "link")) or (re.search(r'<link[^>]*href="([^"]+)"', it) or [None, ""])[1]
        d = _tag(it, "pubDate") or _tag(it, "dc:date") or _tag(it, "updated") or _tag(it, "published")
        try:
            date = parsedate_to_datetime(d).date().isoformat() if "," in d else d[:10]
        except Exception:
            date = ""
        desc = _txt(_tag(it, "description") or _tag(it, "summary"))[:600]
        if titre and lien:
            out.append({"nom": nom, "titre": titre[:300], "url": lien, "date": date, "desc": desc})
    return out


def tout(get):
    """Tous les articles récents de tous les flux (une seule lecture par run)."""
    global _cache
    with _lock:
        if _cache is None:
            res = []
            with ThreadPoolExecutor(12) as ex:
                for lot in ex.map(lambda f: _lire(f[0], f[1], get), FLUX):
                    res += lot
            _cache = res
            print(f"   flux hors grands médias : {len(res)} articles de {len({x['nom'] for x in res})} sources")
        return _cache


def cherche(textes, get, limite=25):
    """Articles des flux qui parlent du sujet : au moins 2 mots-clés du sujet (ou de ses traductions) dans le titre/résumé."""
    cles = set()
    for w in _plat(" ".join(textes)).split():
        if len(w) > 3 and w not in VIDES:
            cles.add(w)
            cles.update(ALIAS.get(w, "").split())
    if not cles:
        return []
    notes = []
    for a in tout(get):
        mots = set(_plat(a["titre"] + " " + a["desc"]).split())
        sc = len(cles & mots)
        if sc >= 2:
            notes.append((sc, a))
    notes.sort(key=lambda x: -x[0])
    out, par = [], {}
    for sc, a in notes:
        if par.get(a["nom"], 0) >= 3:
            continue
        par[a["nom"]] = par.get(a["nom"], 0) + 1
        out.append(a)
        if len(out) >= limite:
            break
    return out
