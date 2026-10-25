"""Fabrication GRATUITE de la miniature 1280x720.

Ordre des sources d'image (de la plus authentique à la moins) :
1. VRAIE photo libre de droits (Wikimedia Commons), choisie par Gemini parmi plusieurs candidates ;
2. image générée par Gemini (si le quota gratuit le permet) ;
3. image générée par Pollinations (FLUX, gratuit, sans clé).
Le texte est TOUJOURS incrusté ici, avec une vraie police : le texte écrit par une IA fait faux à coup sûr.
"""
from __future__ import annotations

import io
import os
import random
import re
import urllib.parse

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, features

from . import config, llm

W, H = 1280, 720
FONT_DIR = os.path.join(os.path.expanduser("~"), ".cache", "osint-fonts")
FONTS = {
    "latin": "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf",
    "arabic": "https://raw.githubusercontent.com/google/fonts/main/ofl/lalezar/Lalezar-Regular.ttf",
}
HDR = {"User-Agent": config.UA}


# ------------------------------------------------------------------ polices
def font(kind, size):
    os.makedirs(FONT_DIR, exist_ok=True)
    path = os.path.join(FONT_DIR, os.path.basename(FONTS[kind]))
    if not os.path.exists(path):
        r = requests.get(FONTS[kind], timeout=30)
        r.raise_for_status()
        open(path, "wb").write(r.content)
    return ImageFont.truetype(path, size)


def _is_arabic(t):
    return any("؀" <= c <= "ۿ" for c in t)


def _shape(t):
    """Arabe : Pillow avec raqm gère seul la liaison des lettres ; sinon on la fait à la main."""
    if not _is_arabic(t) or features.check("raqm"):
        return t
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(t))
    except Exception:
        return t


# ------------------------------------------------------------------ sources d'image
def _get_img(url, timeout=40):
    r = requests.get(url, headers=HDR, timeout=timeout)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    im.load()
    return im.convert("RGB")


def commons_candidates(queries, limit=8):
    """Photos réelles, paysage, assez grandes, sous licence libre."""
    out, seen = [], set()
    for q in queries[:5]:
        try:
            r = requests.get("https://commons.wikimedia.org/w/api.php", headers=HDR, timeout=20, params={
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 15,
                "gsrsearch": f"filetype:bitmap {q}", "prop": "imageinfo", "iiprop": "url|size|extmetadata|mime",
                "iiurlwidth": 1600})
            pages = (r.json().get("query") or {}).get("pages") or {}
        except Exception as e:
            print(f"   ! Wikimedia indisponible ({str(e)[:60]})")
            continue
        for p in sorted(pages.values(), key=lambda p: p.get("index", 99)):
            ii = (p.get("imageinfo") or [{}])[0]
            w, h = ii.get("width", 0), ii.get("height", 0)
            if ii.get("mime") not in ("image/jpeg", "image/png") or w < 1100 or h < 600 or w / max(h, 1) < 1.25:
                continue
            if p["title"] in seen:
                continue
            seen.add(p["title"])
            md = ii.get("extmetadata") or {}
            strip = lambda k: re.sub(r"<[^>]+>", "", (md.get(k) or {}).get("value", "")).strip()
            out.append({"titre": p["title"], "url": ii.get("thumburl") or ii.get("url"), "page": ii.get("descriptionurl", ""),
                        "auteur": strip("Artist")[:80] or "inconnu", "licence": strip("LicenseShortName") or "libre",
                        "desc": strip("ImageDescription")[:160]})
            if len(out) >= limit:
                return out
    return out


def pick_real_photo(cands, sujet, concept):
    """Gemini regarde les photos et classe celles qui collent vraiment au sujet (liste vide si aucune)."""
    from google.genai import types
    parts, kept = [], []
    for c in cands[:6]:
        try:
            im = _get_img(c["url"].replace("/1600px-", "/480px-"), timeout=20)
            buf = io.BytesIO()
            im.thumbnail((480, 480))
            im.save(buf, "JPEG", quality=80)
            parts.append(types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg"))
            kept.append(c)
        except Exception:
            continue
    if not kept:
        return None
    listing = "\n".join(f"Image {i}: {c['titre']} — {c['desc']}" for i, c in enumerate(kept))
    p = f"""SUJET D'UNE VIDÉO : {sujet}
IMAGE VOULUE POUR LA MINIATURE : {concept}
Voici {len(kept)} photos réelles (dans l'ordre). Laquelle ferait une miniature YouTube FORTE et DIRECTEMENT liée au sujet ?
Critères : lien évident avec le sujet (bonne personne, bon lieu, bon objet), un point focal net, pas de collage, pas de schéma,
pas de carte, pas de texte incrusté, pas de photo d'archive hors-sujet. Si aucune ne convient vraiment, réponds -1.
Classe les photos qui conviennent, de la meilleure à la moins bonne ; écarte celles qui ne conviennent pas (liste vide si aucune).
Réponds en JSON : {{"classement": [int], "raison": str}}
{listing}"""
    try:
        j = llm.parse_json(llm.text(llm.ask([p] + parts, temperature=0.0, json_mode=True, fatal=False)))
        rank = j.get("classement") if isinstance(j, dict) else None
        if rank is None and isinstance(j, dict) and "choix" in j:
            rank = [j["choix"]]
        rank = [int(k) for k in (rank or []) if str(k).lstrip("-").isdigit() and 0 <= int(k) < len(kept)]
        if isinstance(j, dict) and j.get("raison"):
            print(f"   photos réelles : {len(rank)} retenue(s) — {str(j['raison'])[:140]}")
    except (Exception, SystemExit) as e:
        print(f"   ! choix de la photo réelle impossible ({str(e)[:60]})")
        return []
    return [kept[k] for k in dict.fromkeys(rank)][:3]


def gemini_image(prompt):
    from google.genai import types
    for model in llm.image_models()[:3]:
        for i in range(len(llm.keys())):
            try:
                r = llm.client(i).models.generate_content(
                    model=model, contents=prompt,
                    config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"], safety_settings=llm.SAFETY))
                for part in r.candidates[0].content.parts:
                    if getattr(part, "inline_data", None) and part.inline_data.data:
                        return Image.open(io.BytesIO(part.inline_data.data)).convert("RGB"), model
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "NOT_FOUND" in msg or "404" in msg[:40]:
                    continue
                print(f"   ! {model} : {msg[:80]}")
                break
    return None, None


def pollinations(prompt):
    for seed in random.sample(range(1, 99999), 2):
        # Pollinations ajoute son logo en bas à droite malgré nologo : on demande 80 px de plus et on coupe la bande du bas
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt[:900])
               + f"?width={W}&height={H + 80}&model=flux&nologo=true&private=true&enhance=false&seed={seed}")
        try:
            im = _get_img(url, timeout=150)
            if im is not None:
                cut = max(40, round(im.height * 80 / (H + 80)))
                im = im.crop((0, 0, im.width, im.height - cut))
            return im, "pollinations / flux"
        except Exception as e:
            print(f"   ! Pollinations ({str(e)[:60]})")
    return None, None


# ------------------------------------------------------------------ mise en page
def cover(im, focus_y=0.4):
    r = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
    x = (im.width - W) // 2
    y = int((im.height - H) * focus_y)
    return im.crop((x, y, x + W, y + H))


def photo_finish(im, generated):
    """Rend l'image moins « IA » : couleurs moins saturées, léger grain, vignette douce."""
    if generated:
        im = ImageEnhance.Color(im).enhance(0.82)
        im = ImageEnhance.Contrast(im).enhance(1.05)
        noise = Image.effect_noise((W, H), 18).convert("RGB")
        im = Image.blend(im, noise, 0.045)
        im = im.filter(ImageFilter.UnsharpMask(radius=1, percent=40, threshold=3))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse((-W * 0.2, -H * 0.25, W * 1.2, H * 1.25), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(120))
    return Image.composite(im, Image.new("RGB", (W, H), (0, 0, 0)), mask)


def _hex(c, default):
    m = re.search(r"#?([0-9a-fA-F]{6})\b", c or "")
    return "#" + m.group(1) if m else default


def _shade(im, zone):
    """Assombrit progressivement la zone du texte pour qu'il reste lisible sur mobile."""
    g = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(g)
    for k in range(256):
        a = int(200 * (1 - k / 255) ** 1.6)
        if zone == "left":
            x = int(W * 0.62 * k / 255); d.line([(x, 0), (x, H)], fill=a, width=4)
        elif zone == "right":
            x = W - int(W * 0.62 * k / 255); d.line([(x, 0), (x, H)], fill=a, width=4)
        elif zone == "top":
            y = int(H * 0.55 * k / 255); d.line([(0, y), (W, y)], fill=a, width=4)
        else:
            y = H - int(H * 0.55 * k / 255); d.line([(0, y), (W, y)], fill=a, width=4)
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, g)


def draw_text(im, text, accent_word, accent, zone, tout=False):
    text = " ".join(text.split()[:3])
    if not text:
        return im
    arabic = _is_arabic(text)
    kind = "arabic" if arabic else "latin"
    words = []
    for w in (text.split() if arabic else text.upper().split()):
        if words and not re.search(r"\w", w):       # « 30 % », « 5 € » : le symbole reste collé au chiffre
            words[-1] += "\u202f" + w
        else:
            words.append(w)
    accent_word = (accent_word or "").strip()
    acc_idx = next((i for i, w in enumerate(words) if accent_word and accent_word.upper() in w.upper()), len(words) - 1)
    box_w = W * (0.52 if zone in ("left", "right") else 0.9)
    box_h = H * (0.8 if zone in ("left", "right") else 0.42)
    # lignes : un mot par ligne à gauche/droite, sinon tout sur une ligne si ça tient
    layouts = [[[w] for w in words]] if zone in ("left", "right") else [[words], [[w] for w in words]]
    best = None
    for lay in layouts:
        lines = [" ".join(l) for l in lay]
        for size in range(260, 40, -6):
            f = font(kind, size)
            sizes = [f.getbbox(_shape(l)) for l in lines]
            lw = max(b[2] - b[0] for b in sizes)
            lh = sum(b[3] - b[1] for b in sizes) + int(size * 0.12) * (len(lines) - 1)
            if lw <= box_w and lh <= box_h:
                if not best or size > best[1]:
                    best = (lay, size)
                break
    lay, size = best or (layouts[-1], 60)
    f = font(kind, size)
    gap = int(size * 0.12)
    heights = [f.getbbox(_shape(" ".join(l)))[3] - f.getbbox(_shape(" ".join(l)))[1] for l in lay]
    total = sum(heights) + gap * (len(lay) - 1)
    margin = 56
    y = {"top": margin, "bottom": H - margin - total}.get(zone, (H - total) // 2)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds, dl = ImageDraw.Draw(shadow), ImageDraw.Draw(layer)
    idx = 0
    sw = max(3, size // 28)
    space = f.getlength(" ")
    for line, lh in zip(lay, heights):
        s = _shape(" ".join(line))
        b = f.getbbox(s)
        lw = b[2] - b[0]
        x = {"left": margin, "right": W - margin - lw}.get(zone, (W - lw) // 2)
        if arabic:      # arabe (droite à gauche) : la ligne d'un bloc, accentuée si elle porte le mot-clé
            col = accent if tout or idx <= acc_idx < idx + len(line) else "#FFFFFF"
            ds.text((x - b[0] + 6, y - b[1] + 8), s, font=f, fill=(0, 0, 0, 200))
            dl.text((x - b[0], y - b[1]), s, font=f, fill=col, stroke_width=sw, stroke_fill="#000000")
        else:           # latin : mot par mot, seul le mot-clé prend la couleur d'accent
            cx = x - b[0]
            for k, w in enumerate(line):
                col = accent if tout or idx + k == acc_idx else "#FFFFFF"
                ds.text((cx + 6, y - b[1] + 8), w, font=f, fill=(0, 0, 0, 200))
                dl.text((cx, y - b[1]), w, font=f, fill=col, stroke_width=sw, stroke_fill="#000000")
                cx += f.getlength(w) + space
        y += lh + gap
        idx += len(line)
    im = im.convert("RGBA")
    im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(10)))
    im = Image.alpha_composite(im, layer)
    return im.convert("RGB")


# ------------------------------------------------------------------ contrôle qualité
JUGE = """Voici une image générée pour une miniature YouTube, à partir de ce prompt :
{prompt}
Juge UNIQUEMENT l'image (pas le texte incrusté) :
- "fidele" : montre-t-elle bien ce que décrit le prompt ?
- "nette" : image nette, sans déformations, sans aspect plastique ou bâclé ?
- "propre" : aucun logo, filigrane, texte parasite, bord ou artefact ?
Note de 0 à 10 (7 = publiable). Réponds en JSON : {{"note": int, "fidele": bool, "nette": bool, "propre": bool, "probleme": str}}"""


def juger(img, prompt):
    """Gemini regarde l'image générée et la note. None si le contrôle est indisponible (quota)."""
    from google.genai import types
    buf = io.BytesIO()
    im = img.copy()
    im.thumbnail((640, 640))
    im.save(buf, "JPEG", quality=85)
    try:
        r = llm.ask([JUGE.format(prompt=prompt[:900]), types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")],
                    temperature=0.0, json_mode=True, fatal=False, retries=3)
        j = llm.parse_json(llm.text(r))
        if isinstance(j, dict) and str(j.get("note", "")).strip().lstrip("-").isdigit():
            j["note"] = max(0, min(10, int(j["note"])))
            return j
    except (Exception, SystemExit) as e:
        print(f"   ! contrôle qualité de l'image indisponible ({str(e)[:60]})")
    return None


# ------------------------------------------------------------------ orchestration
def _api_prompt(prompt):
    """Le prompt tel quel, sans les paramètres Midjourney (--ar, --style…) que les générateurs ne comprennent pas."""
    return re.sub(r"\s*--\w+(\s+[^-\s][^\s]*)?", "", prompt or "").strip(" ,")


def _zone(placement):
    p = (placement or "").lower()
    if "haut" in p or "top" in p:
        return "top"
    if "bas" in p or "bottom" in p:
        return "bottom"
    if "droit" in p or "right" in p:
        return "right"
    if "gauche" in p or "left" in p:
        return "left"
    return "top"


def _generees(prompt):
    """Images générées à partir du prompt : modèles d'image Gemini d'abord, puis Pollinations (2 tirages)."""
    img, model = gemini_image(prompt)
    if img is not None:
        yield img, model
    for _ in range(2):
        img, model = pollinations(prompt)
        if img is None:
            break
        yield img, model


def make(L, sujet, out_path, budget_s=None):
    """Miniature 1280x720 générée à partir du prompt_image, avec le texte_miniature incrusté (couleur et placement choisis
    par le générateur). Plusieurs images sont essayées et notées par Gemini ; la meilleure est gardée."""
    import time
    fin = time.monotonic() + (budget_s or float(os.getenv("MINIATURE_BUDGET_S", "300")))
    seuil = int(os.getenv("MINIATURE_NOTE_MIN", "7"))
    prompt = _api_prompt(L.get("prompt_image", ""))
    if not prompt:
        print("   ! pas de prompt d'image : miniature non fabriquée")
        return None
    tm = L.get("texte_miniature") or {}
    zone = _zone(tm.get("placement"))
    couleur = _hex(tm.get("couleur"), "#FFD400")
    best, n = None, 0
    for img, model in _generees(prompt):
        n += 1
        v = juger(img, prompt)
        note = v["note"] if v else None
        print(f"   image {n} ({model}) : " + (f"note {note}/10" + (f" — {str(v.get('probleme'))[:100]}" if v.get("probleme") else "")
                                                if v else "non notée"))
        cur = (note if note is not None else -1, img, {"source": f"image générée ({model})", "note": note,
                                                       "probleme": (v or {}).get("probleme", "")})
        if best is None or cur[0] > best[0]:
            best = cur
        if v is None or note >= seuil or time.monotonic() > fin:
            break
    if best is None:
        print("   ! aucune image obtenue : miniature non fabriquée")
        return None
    note, img, info = best
    im = _shade(cover(img), zone)
    im = draw_text(im, tm.get("texte", ""), "", couleur, zone, tout=True)   # tout le texte dans la couleur choisie
    im.save(out_path, "JPEG", quality=92, optimize=True)
    if info["note"] is not None and info["note"] < seuil:
        info["a_revoir"] = True
    print(f"   miniature : {out_path} ({info['source']}" + (f", note {info['note']}/10)" if info["note"] is not None else ")"))
    return info
