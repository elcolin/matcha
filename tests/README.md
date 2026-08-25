# Tests unitaires

## Objectif
Ce dossier contient les tests unitaires de l'application. La suite actuelle couvre les helpers de sécurité (`app/security.py`).

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
