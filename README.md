# Matcha

Site de rencontre développé dans le cadre du projet 42 **Matcha** : inscription, complétion du profil, recherche/suggestions, consultation de profil, like/match, blocage et signalement de faux comptes, chat et notifications en temps réel.

## Stack

- Backend : Python 3.12 + Flask 3.1 (blueprints), sans ORM.
- Base de données : SQLite, SQL manuscrit (`app/db.py`, schéma dans `app/schema.sql`).
- Templates : Jinja2 (`app/templates/`), CSS custom, JS vanilla minimal.
- Auth : sessions Flask, tokens signés `itsdangerous`, protection CSRF sur toutes les requêtes POST/PUT/PATCH/DELETE.
- Uploads de photos : chaque image est décodée puis réencodée avec Pillow (PNG, JPEG, GIF, WebP ; format déterminé par le contenu, pas par le nom de fichier), métadonnées supprimées (EXIF/GPS, ICC, commentaires), nom de fichier aléatoire, 5 MB max (contrôle côté client et côté serveur).
- Temps réel : polling léger (chat 5s, notifications SSE), statut online/offline avec pastille visuelle et polling 5s.
- Géolocalisation : `geopy` avec le géocodeur Nominatim (OpenStreetMap, timeout 10 s) pour résoudre la ville depuis les coordonnées GPS ou la saisie manuelle. Nécessite un accès réseau ; en cas d'indisponibilité, la mise à jour du profil est refusée proprement (503). Distance entre profils : formule de haversine (sans API externe).

Détails complets dans [`CLAUDE.md`](./CLAUDE.md).

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Les outils de `scripts/` (génération de profils `Faker`, bios via `transformers`/`torch`) ont leurs propres dépendances, plus lourdes, non requises par l'app ni par les tests :

```bash
pip install -r requirements-dev.txt
```

Créer un fichier `.env` à la racine (jamais commité) avec au minimum :

```
SECRET_KEY=...              # clé de signature des sessions/tokens/CSRF
DATABASE_PATH=...           # optionnel, défaut instance/matcha.db
SESSION_COOKIE_SECURE=false # true en production (HTTPS)
SMTP_SERVER=...             # credentials to send verification emails
SMTP_PORT=...
SMTP_USERNAME=...
SMTP_PASSWORD=...
PI_IMAGES=...               # to generate profile photos
PLACEHOLDER_PATH=...        # placeholder if images API doesn't work
```

## Lancer le serveur de développement

```bash
python run.py
```

Le serveur écoute sur `http://localhost:8000`.

## Tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Les tests tournent aussi en CI GitHub Actions sur chaque push/PR (`.github/workflows/unit-tests.yml`).

## Outils de développement (`scripts/`)

CLI dev-only, lancés manuellement, jamais démarrés par l'application Flask :

- `python scripts/generate_users.py [count]` — génère des profils factices avec `Faker` (au moins 500 pour l'évaluation, selon les contraintes du sujet). Les photos sont téléchargées depuis l'API iNaturalist (`api.inaturalist.org`) ; en cas d'échec, des photos de remplacement sont utilisées.
- `python scripts/generate_users.py [count] ai` — génère des profils dont la biographie est écrite par le modèle, `SmolLM2-360M-Instruct` par défaut.
- `python scripts/generate_users.py cleanup START END` — supprime les données des utilisateurs dont les identifiants sont compris entre `START` et `END`. `python scripts/generate_users.py cleanall` supprime les données de tous les utilisateurs.
- `scripts/generate_chat.py [count]` — seed des conversations réalistes entre utilisateurs matchés, via un modèle Ollama local (nécessite `ollama serve` avec un modèle instruct léger, ex. `qwen2.5:3b-instruct`).
- `scripts/create_bot_user.py <user_id> [suffix]` — crée un compte "bot" (`username` préfixé `bot_`) et le matche (like mutuel) avec un utilisateur cible.
- `scripts/chat_bot_responder.py [username]` — fait répondre en temps réel un utilisateur "bot" aux messages de ses partenaires matchés non bloqués, en réutilisant les mêmes helpers Ollama que `generate_chat.py` ; nécessite aussi `ollama serve`.

Chaque script expose ses propres sous-commandes `cleanup`/`cleanall` pour supprimer les données générées ; voir l'en-tête de chaque fichier pour le détail.

## Déploiement

Pas de déploiement en ligne pour le moment.
