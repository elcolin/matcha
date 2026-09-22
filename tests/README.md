# Tests unitaires

## Objectif
Ce dossier contient les tests unitaires de l'application. La suite actuelle couvre :

- `app/security.py` (`test_security.py`, `test_csrf.py`) — hash/vérification de mot de passe, force du mot de passe, tokens signés (email, reset, CSRF) et leur intégration (`csrf_protect`) sur les formulaires HTML/JSON.
- `app/utils.py` — popularité, blocage, match, `login_required`, notifications.
- `app/auth/routes.py` — verrouillage anti-bruteforce (`_is_locked_out`).
- `app/auth/routes.py::request_password_reset` (`test_auth_reset.py`) — non-fuite d'existence de compte : le flux token/email s'exécute toujours pour un compte existant, et la réponse HTTP est indiscernable entre un compte existant et un compte inconnu.
- Non-fuite d'existence de compte lors d'une panne d'envoi d'email (`test_auth_email_errors.py`, régression issue #61 sur `app/auth/routes.py::request_password_reset` et `send_verification_email`) — un échec `send_email` ne doit jamais se traduire par un statut HTTP différent entre un compte existant et un compte inconnu.
- `app/match/routes.py` (`test_match.py`, `test_match_routes.py`) — distance, compatibilité de genre, filtres/tri des suggestions, tags partagés, `candidate_profiles`.
- `app/profile/data.py` — mise à jour email/prénom/nom (`UserUpdater`).
- `app/profile/geolocation.py` — extraction ville/quartier depuis les coordonnées GPS, validation de ville (géocodeur mocké, aucun appel réseau).
- `app/profile/routes.py` — validation/upload de photo (`_save_uploaded_photo`), mise à jour de profil (`_update_profile` : gender/preference/tags/géolocalisation).
- `app/notifications/routes.py` (`test_notification.py`) — création des notifications (vue de profil, like reçu, match, unlike) via `app/utils.add_notification`, compteur non-lu, marquage lu, rendu de la page, protection `login_required`.
- Notifications liées au blocage (`test_notifications.py`, via des requêtes client sur `app/profile/routes.py`) — aucune notification de vue/unlike entre utilisateurs bloqués.
- Présence et notification de message en chat (`test_chat.py`, via `app/chat/routes.py`) — fraîcheur de `_is_viewing_chat`, upsert de la route de ping de présence, notification `message_received` envoyée seulement si le destinataire ne regarde pas activement la conversation.
- `test_flash_xss.py` — échappement HTML des messages flash (régression XSS sur `app/templates/components/base.html`).
- Fonctions pures du seed de conversations via Ollama (`test_generate_chat.py`, `scripts/generate_chat.py`) et du répondeur de chat bot dev-only (`test_chat_bot_responder.py`, `scripts/chat_bot_responder.py`) — y compris, via mocks (`unittest.mock.patch`) de `query_all`/`call_ollama`, la construction du prompt de réponse (`build_reply_prompt`) et le garde-fou contre les générations où le modèle répond avec le préfixe de l'autre interlocuteur.

`tests/helpers.py` fournit `DBTestCase`, une base commune qui pousse un contexte Flask adossé à une base SQLite temporaire (chargée depuis le vrai `app/schema.sql`), sans jamais toucher `instance/matcha.db`.

Hors périmètre pour l'instant (tests d'intégration/routes HTTP, pas des tests unitaires) : les routes Flask elles-mêmes non listées ci-dessus (`register`, `login`, `send_message`, etc.), qui mêlent session/requête HTTP et logique métier.

## Exécution locale
Depuis la racine du dépôt :

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```

## Exécution en CI
Les tests sont lancés automatiquement sur chaque `push` et `pull_request` via :

- `.github/workflows/unit-tests.yml`

## Maintenance
- Ajouter de nouveaux fichiers au format `test_*.py` dans `tests/`.
- Garder des tests déterministes (pas de dépendance réseau, pas d'état externe).
- Mettre à jour ce README et le workflow si la commande de test change.
- Vérifier localement la suite avant de pousser.

## Mocker les accès DB/réseau (`unittest.mock.patch`)
Pour tester une fonction qui appelle `app.db.query_all`/`query_one`/`execute` ou un service
externe (ex. `scripts.generate_chat.call_ollama`) sans base de données ni réseau réels,
patcher le nom **tel qu'importé dans le module testé**, pas à sa source. Exemple
(`tests/test_chat_bot_responder.py`, `GenerateBotReplyPromptRegressionTests`) :

```python
from unittest.mock import patch

@patch("scripts.chat_bot_responder.call_ollama")
@patch("scripts.chat_bot_responder.query_all")
def test_something(self, mock_query_all, mock_call_ollama):
    mock_query_all.return_value = [{"sender_id": 2, "content": "..."}]
    mock_call_ollama.return_value = "B: ..."
    ...
```

Les décorateurs `@patch` s'appliquent de bas en haut, donc les mocks arrivent en
paramètres dans le même ordre (le plus proche de la fonction en premier).
