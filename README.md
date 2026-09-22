# Matcha

Site de rencontre développé dans le cadre du projet 42 **Matcha** : inscription, complétion du profil, recherche/suggestions, consultation de profil, like/match, chat et notifications en temps réel.

## Stack

- Backend : Python 3.12 + Flask 3.1 (blueprints), sans ORM.
- Base de données : SQLite, SQL manuscrit (`app/db.py`, schéma dans `app/schema.sql`).
- Templates : Jinja2 (`app/templates/`), CSS custom, JS vanilla minimal.
- Auth : sessions Flask, tokens signés `itsdangerous`, protection CSRF sur toutes les requêtes POST/PUT/PATCH/DELETE.

Détails complets dans [`CLAUDE.md`](./CLAUDE.md).

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Créer un fichier `.env` à la racine (jamais commité) avec au minimum :

```
SECRET_KEY=...              # clé de signature des sessions/tokens/CSRF
DATABASE_PATH=...           # optionnel, défaut instance/matcha.db
SESSION_COOKIE_SECURE=false # true en production (HTTPS)
SMTP_SERVER=...
SMTP_PORT=...
SMTP_USERNAME=...
SMTP_PASSWORD=...
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

- `scripts/generate_users.py [count]` — génère des profils factices via `Faker` (au moins 500 requis pour l'évaluation, cf. contraintes du sujet).
- `scripts/generate_chat.py [count]` — seed des conversations réalistes entre utilisateurs matchés, via un modèle Ollama local (nécessite `ollama serve` avec un modèle instruct léger, ex. `qwen2.5:3b-instruct`).
- `scripts/create_bot_user.py <user_id> [suffix]` — crée un compte "bot" (`username` préfixé `bot_`) et le matche (like mutuel) avec un utilisateur cible.
- `scripts/chat_bot_responder.py [username]` — fait répondre en temps réel un utilisateur "bot" aux messages de ses partenaires matchés non bloqués, en réutilisant les mêmes helpers Ollama que `generate_chat.py` ; nécessite aussi `ollama serve`.

Chaque script expose ses propres sous-commandes `cleanup`/`cleanall` pour supprimer les données générées ; voir l'en-tête de chaque fichier pour le détail.

## Déploiement

Pas de déploiement en ligne pour le moment.
