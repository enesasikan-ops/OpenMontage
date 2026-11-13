# Jarvis — assistant personnel (local + Claude en renfort)

Jarvis tourne **chez toi**, sur un Mac mini (ou n'importe quel Mac Apple Silicon) :

```
🎤 ta voix ──► Whisper (local) ──► 🦙 modèle local (Ollama)
                                      │  question simple  → répond tout seul (gratuit, privé)
                                      │  question difficile → ☁️ Claude (API Anthropic)
                                      ▼
🔊 Piper (voix locale) ◄────────── réponse
```

- **Conversation libre**, ton franc et direct, mémoire de ce que tu lui apprends.
- **Garde-fou sur les actions** : avant toute action sensible (aujourd'hui : effacer
  sa mémoire ; demain : envoyer un mail, ouvrir une porte…), Jarvis dit ce qu'il va
  faire et attend ton « oui ».
- **Claude en renfort** : facultatif. Sans clé API, Jarvis fonctionne 100 % en local.

## 1. Choisir le modèle local selon la RAM du Mac

| RAM du Mac | Modèle conseillé (`JARVIS_MODELE_LOCAL`) | Remarque |
|---|---|---|
| 16 Go | `qwen3:8b` ou `llama3.1:8b` | Correct pour les questions simples |
| 24–32 Go | `mistral-small3.2` *(par défaut)* | Bon en français, bon avec les outils |
| 64 Go et + | `llama3.3:70b` | Très bon, plus lent |

Le modèle doit savoir utiliser des **outils** (« tools » sur ollama.com) :
c'est ce qui lui permet d'appeler Claude, de lire l'heure, de retenir des infos.

## 2. Installation (une seule fois)

Prérequis : [Homebrew](https://brew.sh). Puis, dans le Terminal :

```bash
cd jarvis
./installer.sh
```

Le script installe Python, Ollama, les dépendances, la voix française
(`fr_FR-siwis-medium`) et télécharge le modèle local. Compte 10 à 30 minutes
selon la connexion (le modèle pèse plusieurs Go).

## 3. Ajouter Claude (facultatif, recommandé)

1. Crée une clé sur <https://console.anthropic.com> (c'est séparé de l'abonnement
   Claude.ai : paiement à l'usage, environ 3 centimes par question difficile
   avec Claude Opus 5.5). Fixe un plafond mensuel dans la console.
2. Ouvre le fichier `.env` et colle la clé après `ANTHROPIC_API_KEY=`.

Pour dépenser moins, mets `JARVIS_MODELE_CLAUDE=claude-sonnet-5-5` (environ deux fois
moins cher).

## 4. Lancer Jarvis

```bash
.venv/bin/python main.py          # au clavier (idéal pour tester)
.venv/bin/python main.py --voix   # à la voix : Entrée pour parler, Entrée pour finir
```

Exemples à essayer :
- « Quelle heure est-il ? » → outil local
- « Retiens que je bois mon café sans sucre » → mémoire (`~/.jarvis/memoire.json`)
- « Demande à Claude un plan pour lancer ma chaîne YouTube » → renfort Claude
- « Oublie ce que tu sais sur le café » → demande ta confirmation
- « Au revoir » → quitte

## Matériel conseillé pour la voix

Le Mac mini n'a pas de micro et son haut-parleur est faible : branche un
**micro-haut-parleur USB de conférence** (Jabra Speak, Anker PowerConf…). Il capte
la voix de loin et annule l'écho.

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
```

Les tests simulent Ollama et Claude : ils ne coûtent rien et ne demandent aucune clé.

## Prochaines étapes

- Mot de réveil « Hey Jarvis » (openWakeWord a un modèle prêt à l'emploi).
- Bot Telegram pour lui parler depuis le téléphone, avec Tailscale pour y accéder hors de chez toi.
- Outils Notion (QG « Jarvis — QG » et base « Tâches Jarvis »), agenda, domotique (Home Assistant).
- Chaque nouvel outil qui **agit** (envoyer, supprimer, payer, ouvrir) reçoit une confirmation.
