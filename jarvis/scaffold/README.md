# Générateur de code (scaffold)

Un fichier de configuration YAML décrit ce que tu veux ; le générateur écrit les ~80 %
de code répétitif. Tu n'écris que la logique métier, dans des **zones manuelles** qui
survivent aux régénérations.

```bash
python -m scaffold packs                                 # packs disponibles
python -m scaffold exemple jarvis-capacite > marees.yaml # config d'exemple
python -m scaffold generer marees.yaml --simuler         # plan, sans rien écrire
python -m scaffold generer marees.yaml                   # génère
python -m scaffold generer marees.yaml --update --diff   # régénère, garde ton code
```

## Architecture

```
          marees.yaml (ta config)
                 │
                 ▼
   ┌──────────── MOTEUR (scaffold/core.py) — ne connaît aucune architecture ──┐
   │ 1. charger      YAML → dict                                              │
   │ 2. valider      contre le schéma DU PACK (toutes les erreurs d'un coup)  │
   │ 3. contexte     config + noms dérivés (snake, kebab, Pascal, camel)      │
   │ 4. rendre       modèles Jinja2 du pack                                   │
   │ 5. planifier    créer / identique / ignorer / écraser / mettre à jour    │
   │ 6. écrire       ou --simuler ; jamais hors du dossier cible              │
   └──────────────────────────────────────────────────────────────────────────┘
                 ▲
     PACK DE MODÈLES (scaffold/packs/<nom>/) — tout le spécifique est ici
       pack.yaml      schéma de config + liste des fichiers à produire
       *.j2           modèles (Jinja2)
       exemple.yaml   config d'exemple
```

Le moteur et les packs sont séparés : pour une autre architecture (un microservice
FastAPI, un module Node, un composant React…), tu **ajoutes un pack**, sans toucher au moteur.

## Les 20 % manuels : zones protégées

Dans les fichiers générés, la logique se met entre deux marqueurs :

```python
def horaires_marees(port=None) -> str:
    # >>> manuel: horaires_marees
    ...ton code...
    # <<< manuel: horaires_marees
```

Avec `--update`, le générateur re-rend tout le fichier (nouvelles actions, nouveaux
paramètres…) puis **réinjecte le contenu de chaque zone** à l'identique. Si une zone
disparaît du modèle (action supprimée de la config), il te prévient pour que tu
récupères ce code. Marqueurs acceptés : `# >>> manuel: id` et `<!-- >>> manuel: id -->`.

Modes d'écriture :

| Situation | Sans option | `--update` | `--force` |
|---|---|---|---|
| Fichier absent | créé | créé | créé |
| Fichier identique | rien | rien | rien |
| Fichier différent | **ignoré** (rien n'est perdu) | régénéré, zones gardées | écrasé |

## Créer un pack pour ton architecture

1. `mkdir scaffold/packs/mon-service`
2. `pack.yaml` :

```yaml
description: "Microservice FastAPI"
schema:
  nom: {type: str, requis: true, motif: "[a-z][a-z0-9_]*", aide: "ex. commandes"}
  port: {type: int, defaut: 8000}
  base_de_donnees: {type: bool, defaut: true}
  endpoints:
    type: list
    requis: true
    unique: chemin
    elements:
      chemin: {type: str, requis: true}
      methode: {type: str, defaut: GET, choix: [GET, POST, PUT, DELETE]}
fichiers:
  - {modele: app.py.j2,        sortie: "services/{{ noms.kebab }}/app.py"}
  - {modele: test_app.py.j2,   sortie: "services/{{ noms.kebab }}/tests/test_app.py"}
  - {modele: Dockerfile.j2,    sortie: "services/{{ noms.kebab }}/Dockerfile"}
  - {modele: db.py.j2,         sortie: "services/{{ noms.kebab }}/db.py", si: "base_de_donnees"}
notes:
  - "Lance : docker build services/{{ nom }}"
```

3. Les modèles `*.j2` : Jinja2 avec les filtres `snake`, `kebab`, `pascal`, `camel` et
   `pyrepr` (littéral Python sûr), et la variable `noms` (`noms.snake`, `noms.pascal`…).
   Mets des zones `# >>> manuel: <id>` là où le code métier ira.
4. Ajoute un `exemple.yaml`, puis teste : `python -m scaffold generer exemple.yaml --simuler`.

Règles du schéma : `type` (str, int, float, bool, list, dict), `requis`, `defaut`,
`motif` (regex) + `aide`, `choix`, et pour les listes `elements`, `non_vide`, `unique`.
Toute clé inconnue est signalée (pour attraper les fautes de frappe).

## Pack fourni : `jarvis-capacite`

Une nouvelle capacité Jarvis = un module d'outils (`build_tools()`), ses tests et sa doc,
dans `plugins/<nom>/` : Jarvis la charge automatiquement au démarrage. Les actions
`sensible: true` reçoivent d'office une **confirmation**, et un test vérifie qu'elle est là.
Le mentor de nuit utilise aussi ce générateur pour partir d'un squelette propre.
