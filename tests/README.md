# Tests unitaires

## Objectif
Ce dossier contient les tests unitaires de l'application. La suite actuelle couvre les helpers de sécurité (`app/security.py`), l'échappement HTML des messages flash (`test_flash_xss.py`, régression XSS sur `app/templates/components/base.html`), les fonctions pures du seed de conversations via Ollama (`test_generate_chat.py`, `scripts/generate_chat.py`) et celles du répondeur de chat bot dev-only (`test_chat_bot_responder.py`, `scripts/chat_bot_responder.py`) — y compris, via mocks (`unittest.mock.patch`) de `query_all`/`call_ollama`, la construction du prompt de réponse (`build_reply_prompt`) et le garde-fou contre les générations où le modèle répond avec le préfixe de l'autre interlocuteur.

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
