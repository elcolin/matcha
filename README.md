# Matcha

Site de rencontre développé pour le projet 42 **Matcha** — partie obligatoire uniquement (aucun bonus).
Stack volontairement compacte et accessible pour débutants : **Flask** (micro-framework, sans ORM) + **SQLite** (requêtes SQL manuelles) + **Bootstrap 5** (via CDN, aucune dépendance front à installer).

## Pourquoi ce stack

- **Flask** est listé par le sujet comme micro-framework valide : il fournit un routeur et le templating Jinja2, mais ni ORM, ni gestion d'utilisateurs, ni validateurs — tout ça est écrit à la main dans le projet, comme demandé.
- **SQLite** via le module standard `sqlite3` : pas de serveur de base de données à installer, les requêtes SQL sont écrites à la main dans `app/db.py` et les routes.
- **Bootstrap 5** est chargé par CDN dans `app/templates/base.html` : aucune dépendance npm/build front, juste du HTML/CSS/JS simple — idéal pour rester lisible et facile à modifier.

## Structure du projet

```
matcha/
├── run.py                     # point d'entrée (flask run / python run.py)
├── requirements.txt           # flask, python-dotenv, watchdog
├── app/
│   ├── __init__.py            # app factory, blueprints, session, notifications
│   ├── config.py              # configuration (clé secrète, DB, uploads, TTL tokens...)
│   ├── db.py                  # connexion SQLite + helpers query_one/query_all/execute
│   ├── schema.sql             # schéma complet de la base (créé automatiquement au démarrage)
│   ├── security.py            # hash de mot de passe, tokens signés, règles de robustesse
│   ├── utils.py                # APIError, login_required, popularité, notifications...
│   ├── routes.py              # page d'accueil
│   ├── auth/routes.py         # inscription, vérification email, connexion, mot de passe oublié
│   ├── profile/routes.py      # profil (édition, photos), like/unlike/bloquer/signaler, notifications
│   ├── match/routes.py        # suggestions de profils + recherche avancée (tri/filtres)
│   ├── chat/routes.py         # messagerie + flux temps réel (Server-Sent Events)
│   ├── users/routes.py        # blueprint utilisateur (minimal)
│   ├── templates/
│   │   ├── base.html          # layout commun (navbar Bootstrap, messages flash, footer)
│   │   ├── index.html         # accueil
│   │   ├── browse.html        # liste des profils suggérés (tri/filtres)
│   │   ├── search.html        # recherche avancée
│   │   ├── profile.html       # vue d'un profil (like, bloquer, signaler...)
│   │   ├── profile_edit.html  # édition de son propre profil + photos
│   │   ├── chat.html          # messagerie en temps réel
│   │   ├── notifications.html # liste des notifications
│   │   ├── auth/               # formulaires inscription/connexion/mot de passe oublié
│   │   └── components/        # fragments réutilisables (carte de profil)
│   └── static/
│       ├── css/style.css      # quelques ajustements visuels par-dessus Bootstrap
│       └── uploads/           # photos de profil uploadées (créé automatiquement, ignoré par git)
└── instance/matcha.db         # base SQLite (créée automatiquement, ignorée par git)
```

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # à créer si besoin, voir "Configuration" ci-dessous
python run.py
```

L'application est servie sur `http://127.0.0.1:5000`. La base SQLite et le dossier d'upload sont créés automatiquement au premier lancement, aucune commande de migration n'est nécessaire.

## Configuration

Toutes les valeurs sensibles sont lues depuis des variables d'environnement (voir `app/config.py`), avec des valeurs par défaut pour le développement local. Créez un fichier `.env` à la racine si vous voulez les personnaliser :

```
SECRET_KEY=change-me-in-production
DATABASE_PATH=instance/matcha.db
EMAIL_VERIFY_TOKEN_TTL_SECONDS=86400
PASSWORD_RESET_TTL_SECONDS=3600
LOGIN_RATE_WINDOW_MINUTES=15
LOGIN_RATE_MAX_FAILS=6
```

`.env` est dans `.gitignore` et ne doit jamais être commité.

> Aucun service d'envoi d'email n'est branché : pour rester simple, les liens de vérification de compte et de réinitialisation de mot de passe sont affichés directement à l'écran (message flash) après inscription / demande de réinitialisation, au lieu d'être envoyés par email. C'est suffisant pour développer et faire la soutenance en local.

## Fonctionnalités implémentées (partie obligatoire du sujet)

- **Inscription / connexion** : email, username, nom, prénom, mot de passe robuste (10 caractères min., majuscule, minuscule, chiffre, caractère spécial, refus des mots de passe courants). Lien de vérification de compte à usage unique. Connexion avec protection anti brute-force (verrouillage temporaire après plusieurs échecs). Déconnexion en un clic. Réinitialisation de mot de passe par lien.
- **Profil utilisateur** : genre, préférence sexuelle, biographie, tags d'intérêt réutilisables, jusqu'à 5 photos (upload réel de fichiers, une photo de profil désignée), géolocalisation GPS avec consentement explicite ou saisie manuelle de la ville/quartier si refusée. Modification du profil à tout moment. Liste des personnes ayant vu son profil et de celles l'ayant "liké". Score de popularité (« fame rating ») calculé à partir des vues, likes et signalements.
- **Browsing** : liste de profils suggérés filtrée par compatibilité de genre/orientation (bisexualité par défaut si non précisé), triée par zone géographique, distance, tags en commun et popularité ; triable et filtrable par âge, localisation, popularité et tags.
- **Recherche avancée** : par tranche d'âge, plage de popularité, ville, tags ; résultats triables/filtrables comme pour le browsing.
- **Vue de profil** : like/unlike, statut "connecté" en cas de like mutuel, statut en ligne / dernière connexion, signalement de faux compte, blocage (disparaît des résultats, plus de notification ni de chat possible), historique de visite enregistré automatiquement.
- **Chat en temps réel** : messagerie entre utilisateurs connectés (like mutuel), diffusion des nouveaux messages via Server-Sent Events (délai < 10s, conforme au sujet).
- **Notifications en temps réel** : like reçu, profil consulté, nouveau message, nouveau match, "unlike" — badge de notifications non lues visible sur toutes les pages, mise à jour en direct via Server-Sent Events.
- **Sécurité** : mots de passe hashés (jamais stockés en clair), requêtes SQL paramétrées (pas d'injection SQL), échappement automatique des templates Jinja2 (pas d'injection HTML/JS), validation serveur de tous les formulaires, upload de photos limité en taille/extension, tokens de vérification/réinitialisation signés et à durée de vie limitée.

## Hors-périmètre (bonus du sujet, non implémenté)

Conformément à la demande, aucune fonctionnalité bonus n'a été développée : pas d'authentification via un fournisseur externe (OAuth), pas de galerie photo avec glisser-déposer/retouche d'image, pas de carte interactive, pas d'appel audio/vidéo, pas de planification de rendez-vous.

## Notes pour la soutenance

- Le serveur de développement Flask (`python run.py`) suffit pour la démo locale ; un serveur de production (Gunicorn, Nginx...) n'a pas été configuré car non requis pour l'évaluation.
- La base de données doit contenir au moins 500 profils distincts pour l'évaluation : un script de génération de jeu de données n'est pas fourni par défaut, à créer si besoin (insertion directe via `app/schema.sql`/`sqlite3`, ou un petit script Python utilisant les helpers de `app/db.py`).
