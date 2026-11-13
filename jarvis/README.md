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
- **Claude en renfort** : via ton abonnement Claude, une clé API, ou pas du tout (100 % local).

## 1. Choisir le modèle local selon la RAM du Mac

| RAM du Mac | Modèle conseillé (`JARVIS_MODELE_LOCAL`) | Remarque |
|---|---|---|
| 16 Go | `qwen3:8b` ou `llama3.1:8b` | Correct pour les questions simples |
| 24–32 Go | `mistral-small3.2` *(par défaut)* | Bon en français, bon avec les outils |
| 48 Go et + | `qwen3:30b-a3b` | Très bon et rapide (n'active qu'une partie du modèle à chaque mot) |
| 64 Go et + (Mac M4 Pro/Max) | `llama3.3:70b` | Très bon, mais lent sans mémoire très rapide |

Le modèle doit savoir utiliser des **outils** (« tools » sur ollama.com) :
c'est ce qui lui permet d'appeler Claude, de lire l'heure, de retenir des infos.

## 2. Installation (une seule fois)

### Le plus simple : laisser Claude Code tout faire

Installe Claude Code (Mac : `curl -fsSL https://claude.ai/install.sh | bash` ;
Windows, dans PowerShell : `irm https://claude.ai/install.ps1 | iex`), lance
`claude`, connecte-toi, puis dis-lui :

> Installe Jarvis en suivant jarvis/README.md, choisis le modèle adapté à cet
> ordinateur, lance les tests, puis optimise le PC avec le script prévu.
> Explique-moi chaque étape et demande-moi avant d'installer quelque chose.

### Sur Mac (Apple Silicon)

Prérequis : [Homebrew](https://brew.sh). Puis, dans le Terminal :

```bash
cd jarvis
./installer.sh
```

### Sur Windows 10/11 (ex. mini-PC AMD Ryzen, 64 Go)

Dans PowerShell, depuis le dossier `jarvis` :

```powershell
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```

L'installeur choisit le modèle selon la mémoire vive : **48 Go et plus →
`qwen3:30b-a3b`** (gros modèle, mais il n'utilise qu'une petite partie de
lui-même à chaque mot, donc il répond vite), 24 Go → `mistral-small3.2`,
moins → `qwen3:8b`. Pour Qwen3, la « réflexion » avant de répondre est coupée
(`JARVIS_REFLEXION_LOCALE=0`) : réponses plus rapides à l'oral.

Ensuite, **optimise le PC** (PowerShell ouvert *en tant qu'administrateur*) :

```powershell
powershell -ExecutionPolicy Bypass -File .\optimiser_windows.ps1
```

Il demande ton accord pour chaque réglage :
1. **Énergie** : performances élevées, plus de mise en veille (l'écran peut s'éteindre).
2. **Ollama** : modèle gardé en mémoire, calcul accéléré, puce graphique AMD utilisée si possible.
3. **Démarrage automatique** du bot Telegram à l'ouverture de session (sans fenêtre, redémarre s'il plante).
4. **Windows Update** : plus de redémarrage automatique quand ta session est ouverte.

Et il t'indique ce qui se règle à la main : la mémoire graphique dans le BIOS
(« UMA Frame Buffer Size » sur 16G) et l'ouverture de session automatique.
Pour tout annuler : `.\optimiser_windows.ps1 -Annuler`.

Compte 20 à 40 minutes au total : les modèles pèsent plusieurs Go.

## 3. Brancher le renfort Claude (facultatif, recommandé)

Choisis le mode avec `JARVIS_RENFORT` dans le fichier `.env` :

| Mode | Comment | Coût |
|---|---|---|
| `abonnement` *(par défaut)* | Passe par **Claude Code** connecté à ton compte Claude | Inclus dans ton abonnement (partage ta limite d'usage) |
| `api` | Passe par une clé API (`ANTHROPIC_API_KEY`) | Environ 3 centimes par question difficile (Claude Opus 5.5) |
| `aucun` | Pas de renfort | Gratuit, 100 % local |

**Mode abonnement**, une seule fois :

```bash
brew install --cask claude-code
claude          # connecte-toi avec ton compte Claude, puis tape /exit
```

Jarvis lance ensuite `claude -p` en coulisses, **sans outils, sans connecteurs et
sans mémoire de session** : Claude ne fait que répondre, il ne peut rien modifier
sur ton ordinateur. Compte 5 à 10 secondes par question. C'est prévu pour ton
usage personnel, sur ta propre machine.

**Mode API** : crée une clé sur <https://console.anthropic.com> (séparé de
l'abonnement, paiement à l'usage, pense à fixer un plafond), colle-la après
`ANTHROPIC_API_KEY=` et mets `JARVIS_RENFORT=api`.

## Confidentialité

- **Rien ne sort** pour le cerveau local, l'écoute (Whisper), la voix (Piper) et la mémoire (`~/.jarvis/memoire.json`).
- **Seules les questions transmises à Claude** partent chez Anthropic, et uniquement quand Jarvis lui passe la main.
- Aucune statistique d'utilisation n'est envoyée (télémétrie Hugging Face désactivée).
- `JARVIS_HORS_LIGNE=1` dans `.env` : **rien ne sort de l'ordinateur**, renfort Claude coupé compris.

## 4. Lancer Jarvis

```bash
.venv/bin/python main.py          # au clavier (idéal pour tester)
.venv/bin/python main.py --voix   # à la voix : Entrée pour parler, Entrée pour finir
```

Sous Windows : `.venv\Scripts\python.exe main.py` (et `--voix`).

Exemples à essayer :
- « Quelle heure est-il ? » → outil local
- « Retiens que je bois mon café sans sucre » → mémoire (`~/.jarvis/memoire.json`)
- « Demande à Claude un plan pour lancer ma chaîne YouTube » → renfort Claude
- « Oublie ce que tu sais sur le café » → demande ta confirmation
- « Au revoir » → quitte

## 5. Parler à Jarvis depuis le téléphone (Telegram)

Tu écris à Jarvis comme à un ami, ou tu lui envoies un **message vocal** : il
répond par écrit, et en vocal si tu lui as parlé. Les actions sensibles
s'affichent avec des boutons **✅ Oui / ❌ Non**.

1. Dans Telegram, ouvre **@BotFather**, envoie `/newbot`, choisis un nom
   (ex. « Jarvis ») et un identifiant qui finit par `bot` (ex. `jarvis_enes_bot`).
2. BotFather te donne un **jeton** : colle-le après `TELEGRAM_TOKEN=` dans `.env`.
3. Lance le bot sur le Mac :
   ```bash
   .venv/bin/python telegram_bot.py
   ```
4. Dans Telegram, ouvre ton bot et envoie `/start`. Il te répond avec ton
   **identifiant** : mets-le après `JARVIS_TELEGRAM_ID=` dans `.env`, puis relance le bot.
   À partir de là, **il ne répond qu'à toi** : toute autre personne est refusée.

Commandes : `/memoire` (ce qu'il sait de toi), `/nouveau` (nouvelle conversation).

À savoir :
- Ça marche **partout** (4G, Wi-Fi, à l'étranger), sans Tailscale ni réglage de la box.
- Le Mac doit rester allumé avec le bot lancé (Réglages → Énergie : empêcher la mise en veille).
- Tes messages passent par les serveurs de Telegram (les conversations avec un
  bot ne sont pas chiffrées de bout en bout). Le cerveau, la voix et la mémoire
  restent sur ton Mac.
- Le jeton donne le contrôle du bot : ne le partage jamais. S'il fuit,
  `/revoke` dans BotFather en génère un nouveau.

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
- Démarrage automatique du bot Telegram à l'allumage du Mac.
- Outils Notion (QG « Jarvis — QG » et base « Tâches Jarvis »), agenda, domotique (Home Assistant).
- Chaque nouvel outil qui **agit** (envoyer, supprimer, payer, ouvrir) reçoit une confirmation.
