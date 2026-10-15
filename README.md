# osint_live_script

Tu tapes un sujet et une durée. Le dépôt cherche, vérifie, écrit le script du live et sort un document de sources séparé.

## Utilisation (GitHub Actions)

1. **Settings → Secrets and variables → Actions** : ajoute `GEMINI_API_KEY` et `YT_API_KEY`. Clés Gemini supplémentaires (comptes/projets distincts) : `GEMINI_API_KEY_2` … `GEMINI_API_KEY_5`. Le script utilise le meilleur modèle sur toutes les clés, puis descend au suivant quand le quota du jour est épuisé. Optionnel : `X_BEARER_TOKEN` (API X payante, 7 derniers jours).
2. **Actions → Générer le script du live → Run workflow** : sujet, durée en minutes, thèse (optionnelle).
3. Télécharge l'artefact `live-script`.

En local : `pip install -r requirements.txt`, puis
`python -m src.main --sujet "..." --duree 20 --these "..."`

Options : `--wpm 145` (mots par minute), `--langue fr|en|…`, `--no-defense`, `--no-interactions`.

## Fichiers produits

| Fichier | Contenu |
|---|---|
| `script_teleprompter.txt` | Texte propre à lire |
| `script_annote.md` | Même texte avec chapitres et marqueurs `[F12]` |
| `sources.md` | Chaque affirmation → fait → source, date, lien, fiabilité, + points à vérifier |
| `donnees.json` | Toutes les sources et tous les faits collectés |

## Comment ça marche

1. **Collecte** : Google News (5 éditions), balayage de 24 médias/agences (Reuters, AP, AFP, BBC, Guardian, NYT, Le Monde…), GDELT, vraies recherches Google via Gemini, YouTube (recherche, stats, transcriptions), Reddit, Hacker News, X (si clé).
2. **Texte intégral** des meilleurs articles (trafilatura).
3. **Extraction de faits** : seulement ce qui est écrit dans la source. Un chiffre absent de la source est corrigé d'après le texte de la source, ou le fait est écarté si la source ne l'établit pas.
4. **Durée** : `durée × 145 mots/min` = budget de mots.
   - Court : les faits sont classés par importance × choc, ceux d'importance 5 ne sont jamais coupés.
   - Long : un chapitre toutes les ~5 min, chacun avec son angle et son procédé de rythme ; si la matière manque, une recherche plus profonde se relance au lieu de remplir.
   - Calage final à ±4 % : coupe de l'accessoire d'abord, ajout de fond (faits en réserve, analyse) jamais de hors-sujet.
5. **Contrôle** : chaque affirmation porte un marqueur de fait ; `sources.md` signale chiffres non retrouvés, chiffres sans source et sources faibles.

## Limites à connaître

- X n'a pas de recherche gratuite : sans `X_BEARER_TOKEN`, les posts X ne sont vus que via la recherche Google.
- Reddit et les transcriptions YouTube bloquent souvent les IP GitHub Actions ; ils sont tentés, ignorés en cas d'échec.
- Les articles payants sont lus en titre seulement.
- Lis `sources.md` avant de diffuser : c'est lui qui te protège (diffamation, strike YouTube).

## Sécurité des clés

Ne mets jamais de clé dans le code. Les clés présentes dans l'ancien notebook sont publiques : révoque-les (Google AI Studio et Google Cloud Console) et recrée-les en secrets.
