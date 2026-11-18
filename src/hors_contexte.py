"""LE PRÉSENTATEUR SE TIENT HORS DU CONTEXTE : jamais « nous », « notre », « nos » (ni « on » au sens de « nous les
Français »). On dit « la France », « les Français », « le gouvernement français »… ; le public, c'est « vous » ;
le présentateur lui-même, « je ».

1. RÈGLE : ajoutée à toutes les consignes d'écriture (live expert, satirique, commentaire d'une vidéo).
2. CONTRÔLE : après l'écriture, chaque paragraphe qui contient encore « nous / notre / nos » (hors citation entre
   guillemets) est réécrit par l'IA, une seule fois ; une réécriture ratée (encore un « nous », texte tronqué) est
   ignorée et le paragraphe d'origine est gardé — jamais de texte perdu. Le nombre restant est écrit dans le journal."""
from __future__ import annotations

import re

REGLE = ("- HORS DU CONTEXTE : le présentateur ne s'inclut JAMAIS dans un pays, un peuple ou un camp. Interdit : « nous », "
         "« notre », « nos », et « on » au sens de « nous les Français » (idem dans la langue du live : « we/our », "
         "« noi/nostro », « نحن/بلادنا »…). Écris « la France », « les Français », « le gouvernement français », « l'Europe », "
         "« les Saoudiens »… ; le public, c'est « vous » ; toi-même, « je ». Exemple refusé : « notre dette nous étrangle ». "
         "Exemple attendu : « la dette de la France étrangle les Français ». Les citations exactes d'autres personnes, "
         "entre guillemets, restent telles quelles.")

PAT = {
    "fr": re.compile(r"\b(nous|notre|nos)\b", re.I),
    "it": re.compile(r"\b(noi|nostro|nostra|nostri|nostre)\b", re.I),
    "en": re.compile(r"\b(we|our|ours|ourselves)\b", re.I),
}
REP = re.compile(r"\[F\d+\]")
QUOTES = re.compile(r"«[^»]*»|“[^”]*”|\"[^\"]*\"")


def fautes(texte: str, lang: str) -> int:
    """Nombre de « nous / notre / nos » hors citations entre guillemets."""
    p = PAT.get((lang or "fr")[:2])
    return len(p.findall(QUOTES.sub(" ", texte or ""))) if p else 0


def corriger(texte: str, lang: str, ask_json) -> tuple[str, int]:
    """(texte corrigé, nombre de « nous » restants). ask_json(prompt) → dict ou None."""
    lg = (lang or "fr")[:2]
    if lg not in PAT or not fautes(texte, lg):
        return texte, 0
    paras = texte.split("\n\n")
    bad = [i for i, p in enumerate(paras) if fautes(p, lg)]
    liste = "\n".join(f"[{k}] {paras[i]}" for k, i in enumerate(bad))
    prompt = f"""Réécris chaque paragraphe numéroté ci-dessous en gardant EXACTEMENT le sens, le ton, la longueur et les
faits, avec une seule différence : le présentateur se tient HORS DU CONTEXTE. Supprime « nous », « notre », « nos »
(et « on » au sens de « nous ») — dans la langue du texte : « we/our », « noi/nostro »… — en écrivant « la France »,
« les Français », le pays ou le groupe concerné, « vous » pour le public, « je » pour le présentateur. Ne touche pas aux
citations exactes entre guillemets ni aux repères [F12] (garde-les tous, au même endroit). Même langue que le texte.
Réponds UNIQUEMENT en JSON : {{"p": ["paragraphe 0 réécrit", "paragraphe 1 réécrit", ...]}} (même nombre, même ordre).

{liste}"""
    try:
        r = ask_json(prompt) or {}
    except Exception:  # noqa: BLE001 - jamais bloquant : le texte d'origine reste
        r = {}
    out = r.get("p") if isinstance(r, dict) else None
    if isinstance(out, list) and len(out) == len(bad):
        for i, new in zip(bad, out):
            new = " ".join(str(new or "").split())
            old = paras[i]
            # gardé seulement si c'est mieux ET complet (jamais un paragraphe raccourci ou vidé par l'IA)
            if (new and fautes(new, lg) < fautes(old, lg) and len(new) >= 0.7 * len(old)
                    and set(REP.findall(old)) <= set(REP.findall(new))):
                paras[i] = new
    texte = "\n\n".join(paras)
    return texte, fautes(texte, lg)
