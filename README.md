# osint_live_script

Tu tapes un sujet et une durée. Le dépôt cherche, vérifie, écrit le script du live et sort un document de sources séparé.

## Utilisation (GitHub Actions)

1. **Settings → Secrets and variables → Actions** : ajoute `GEMINI_API_KEY` et `YT_API_KEY`. Clés Gemini supplémentaires (comptes/projets distincts) : `GEMINI_API_KEY_2` … `GEMINI_API_KEY_5`. Le script utilise le meilleur modèle sur toutes les clés, puis descend au suivant quand le quota du jour est épuisé. Optionnel : `X_BEARER_TOKEN` (API X payante, 7 derniers jours).
2. **Actions → Générer le script du live → Run workflow** : sujet, durée en minutes, thèse (optionnelle).
3. Les fichiers sont enregistrés automatiquement dans le dossier `prompter/` de la branche `main` (un sous-dossier par run : `date_heure_sujet`). Plus d'artefact à télécharger. Le nom du dossier se change en un seul endroit : `OUT_DIR` dans `.github/workflows/generate.yml` (deux occurrences).

En local : `pip install -r requirements.txt`, puis
`python -m src.main --sujet "..." --duree 20 --these "..."`

Options : `--wpm 145` (mots par minute), `--langue fr|en|…`, `--no-defense`, `--no-interactions`.

## Fichiers produits

| Fichier | Contenu |
|---|---|
| `script_teleprompter.txt` | Texte propre à lire |
| `script_annote.md` | Même texte avec chapitres et marqueurs `[F12]` |
| `commentaire_epingle.txt` | Liste des sources citées, avec vraies adresses, prête à coller en commentaire épinglé |
| `sources.md` | Chaque affirmation → fait → source, date, lien, fiabilité, + points à vérifier |
| `miniature.md` | Tout pour la miniature en un seul document : titre + variantes, texte sur l'image, prompt, prompt négatif, à ne pas faire, top 3 concurrents |
| `miniature.jpg` | Miniature 1280×720 prête à l'emploi (vraie photo libre Wikimedia en priorité, sinon image générée gratuitement), texte incrusté |
| `couverture.md` | Ta requête décomposée en points : faits trouvés et cités par point (rien n'est oublié en silence) |
| `STATUT.txt` | Présent seulement s'il y a un souci : point non traité, script trop court/long, miniature manquante |
| `donnees.json` | Toutes les sources et tous les faits collectés |

## 🔗 Vid-o-presse-finder lancé automatiquement

À la fin de chaque run (champ **video_finder** = `oui` par défaut), le workflow prépare 2 à 5 recherches ciblées
(qui a parlé dans les faits cités au script, cibles, points) et lance **Vid-o-presse-finder** sur ce sujet.
Dans le dossier du run : `FINDER.md` (recherches envoyées + ✅ lancé / ❌ raison) et `finder.json`.
Le lot du Finder garde `ORIGINE.json` → Montage LV final se synchronise dessus.

Jeton requis (une fois) : secret **`CHAINE_TOKEN`** dans ce dépôt (même jeton que la chaîne, avec
« Contents : read and write » sur Vid-o-presse-finder) — ou la GitHub App de la chaîne (`CHAINE_APP_ID` / `CHAINE_APP_KEY`).
Sans jeton : le script est livré normalement et `FINDER.md` contient les recherches à coller à la main.

## Comment ça marche

1. **Collecte** : Google News (5 éditions), balayage de 24 médias/agences (Reuters, AP, AFP, BBC, Guardian, NYT, Le Monde…), GDELT, vraies recherches Google via Gemini, YouTube (recherche, stats, transcriptions), Reddit, Hacker News, X (si clé).
2. **Texte intégral** des meilleurs articles (trafilatura).
3. **Extraction de faits** : seulement ce qui est écrit dans la source. Un chiffre absent de la source est corrigé d'après le texte de la source, ou le fait est écarté si la source ne l'établit pas.
4. **Durée** : `durée × 145 mots/min` = budget de mots.
   - Court : les faits sont classés par importance × choc, ceux d'importance 5 ne sont jamais coupés.
   - Long : un chapitre toutes les ~5 min, chacun avec son angle et son procédé de rythme ; si la matière manque, une recherche plus profonde se relance au lieu de remplir.
   - Calage final à ±4 % : coupe de l'accessoire d'abord, ajout de fond (faits en réserve, analyse) jamais de hors-sujet.
5. **Contrôle** : chaque affirmation porte un marqueur de fait ; `sources.md` signale chiffres non retrouvés, chiffres sans source et sources faibles.

- Si un run échoue, la cause est écrite dans `prompter/…/ERREUR.txt` (ou `prompter/ERREUR_date.txt`) et ce qui a été collecté est quand même enregistré.
- Délai global : au bout de 45 min le script s'arrête proprement et garde ce qui est déjà écrit (`DEADLINE_MIN`).

## Vérification croisée automatique

Pour chaque fait fragile (source faible, allégation, signal), le workflow cherche tout seul une source indépendante plus solide (Google News, Bing) et la fait juger : une source n'est acceptée que si une citation exacte se retrouve dans sa page et si les chiffres concordent. Fait confirmé : la citation pointe vers la source la plus solide. Non confirmé : il reste dans le live (rien n'est supprimé), mais attribué à chaque mention et signalé dans `sources.md`. Contredit : le live présente le fait et sa contradiction. Désactivable : `--no-verify`.

## Limites à connaître

- X n'a pas de recherche gratuite : sans `X_BEARER_TOKEN`, les posts X ne sont vus que via la recherche Google.
- Reddit et les transcriptions YouTube bloquent souvent les IP GitHub Actions ; ils sont tentés, ignorés en cas d'échec.
- Les articles payants sont lus en titre seulement.
- Lis `sources.md` avant de diffuser : c'est lui qui te protège (diffamation, strike YouTube).

## Confidentialité

Les fichiers sont commités sur `main` : si le dépôt est public, scripts, sources et prompts le sont aussi. Passe le dépôt en privé (Settings → General → Danger zone → Change visibility). Settings → Actions → General → Workflow permissions : « Read and write ».

## Sécurité des clés

Ne mets jamais de clé dans le code. Les clés présentes dans l'ancien notebook sont publiques : révoque-les (Google AI Studio et Google Cloud Console) et recrée-les en secrets.
