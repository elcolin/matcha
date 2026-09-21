# Tests unitaires

## Objectif
Ce dossier contient les tests unitaires de l'application. La suite actuelle couvre les helpers de sécurité (`app/security.py`, `test_security.py`), les règles de notifications liées au blocage entre utilisateurs (`test_notifications.py`, via des requêtes client sur `app/profile/routes.py`) et la présence/notification de message reçu en chat (`test_chat.py`, via `app/chat/routes.py` : fraîcheur de `_is_viewing_chat`, upsert de la route de ping de présence, notification `message_received` envoyée seulement si le destinataire ne regarde pas activement la conversation).

## Exécution locale
Depuis la racine du dépôt :

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py"
```

## Exécution en CI
Les tests sont lancés automatiquement sur chaque `push` et `pull_request` via :

- `/home/runner/work/matcha/matcha/.github/workflows/unit-tests.yml`

## Maintenance
- Ajouter de nouveaux fichiers au format `test_*.py` dans `/home/runner/work/matcha/matcha/tests`.
- Garder des tests déterministes (pas de dépendance réseau, pas d'état externe).
- Mettre à jour ce README et le workflow si la commande de test change.
- Vérifier localement la suite avant de pousser.
