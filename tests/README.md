# Tests unitaires

## Objectif
Ce dossier contient les tests unitaires de l'application. La suite actuelle couvre :

- `app/security.py` — hash/vérification de mot de passe, force du mot de passe, tokens signés.
- `app/utils.py` — popularité, blocage, match, `login_required`, notifications.
- `app/auth/routes.py` — verrouillage anti-bruteforce (`_is_locked_out`).
- `app/match/routes.py` — distance, compatibilité de genre, filtres/tri des suggestions, tags partagés, `candidate_profiles`.
- `app/profile/data.py` — mise à jour email/prénom/nom (`UserUpdater`).
- `app/profile/geolocation.py` — extraction ville/quartier depuis les coordonnées GPS, validation de ville (géocodeur mocké, aucun appel réseau).
- `app/profile/routes.py` — validation/upload de photo (`_save_uploaded_photo`), mise à jour de profil (`_update_profile` : gender/preference/tags/géolocalisation).
- `app/notifications/routes.py` (`test_notification.py`) — création des notifications (vue de profil, like reçu, match, unlike) via `app/utils.add_notification`, compteur non-lu, marquage lu, rendu de la page, protection `login_required`.
- Notifications liées au blocage (`test_notifications.py`, via des requêtes client sur `app/profile/routes.py`) — aucune notification de vue/unlike entre utilisateurs bloqués.
- Présence et notification de message en chat (`test_chat.py`, via `app/chat/routes.py`) — fraîcheur de `_is_viewing_chat`, upsert de la route de ping de présence, notification `message_received` envoyée seulement si le destinataire ne regarde pas activement la conversation.
- `test_flash_xss.py` — échappement HTML des messages flash (régression XSS sur `app/templates/components/base.html`).

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
