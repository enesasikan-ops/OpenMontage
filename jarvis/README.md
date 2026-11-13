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
.venv/bin/python main.py                 # au clavier (idéal pour tester)
.venv/bin/python main.py --voix          # à la voix : Entrée pour parler, Entrée pour finir
.venv/bin/python main.py --mains-libres  # à la voix, sans clavier : dis « Jarvis »
```

Sous Windows : `.venv\Scripts\python.exe main.py` (mêmes options).

### Mode mains libres

Dis **« Jarvis »** n'importe où dans ta phrase : « Jarvis, quel temps fait-il ? »,
« Qu'en penses-tu, Jarvis ? ». Après sa réponse, il reste à l'écoute 30 secondes
(`JARVIS_ECOUTE_SECONDES`) : tu enchaînes sans redire son nom. « Merci Jarvis »
ou « ce sera tout » le remet en veille. Ce qui ne lui est pas adressé est
ignoré et jeté aussitôt, jamais enregistré. Tout se passe sur l'ordinateur.

Limites connues : il faut un micro correct (idéalement un micro-haut-parleur de
conférence qui annule l'écho) ; dans une pièce bruyante ou avec la télé, il peut
se déclencher à tort ou rater son nom ; on ne peut pas l'interrompre pendant
qu'il parle.

### Personnalité

Par défaut, Jarvis a le style du **majordome du film** : flegmatique, courtois,
pince-sans-rire, il vous vouvoie. Réglages dans `.env` :
- `JARVIS_STYLE=film` ou `ami` (chaleureux, tutoiement) ;
- `JARVIS_TITRE=Monsieur` (ou Madame, Patron…) : comment il s'adresse à toi.
  Vide, il utilise ton prénom ;
- `JARVIS_VOIX_PIPER` : voix d'homme `fr_FR-tom-medium` (défaut) ou de femme
  `fr_FR-siwis-medium`, toutes deux installées dans `voix/`.

Exemples à essayer :
- « Quelle heure est-il ? » → outil local
- « Retiens que je bois mon café sans sucre » → mémoire (`~/.jarvis/memoire.json`)
- « Demande à Claude un plan pour lancer ma chaîne YouTube » → renfort Claude
- « Oublie ce que tu sais sur le café » → demande ta confirmation
- « Au revoir » → quitte

## Ce que Jarvis sait faire (ses compétences)

| Compétence | Exemples | Où vont les données |
|---|---|---|
| **Rappels** | « Rappelle-moi dans 20 minutes de sortir le linge », « Rappelle-moi demain à 8h30 d'appeler le dentiste », « Quels sont mes rappels ? », « Annule le rappel 2 » | Sur ton ordinateur. Ils survivent à un redémarrage et arrivent sur Telegram si le bot tourne. |
| **Calcul exact** | « Combien font 1 250 fois 18 % ? », « Racine de 144 » | Sur ton ordinateur |
| **Météo** | « Quel temps fait-il à Lyon ? », « Il pleut demain ? » | Seul le nom de la ville part vers open-meteo.com (gratuit, sans compte). Règle `JARVIS_VILLE` pour ta ville habituelle. Coupée en mode hors ligne. |
| **Listes** | « Ajoute du lait à la liste de courses », « Lis ma liste », « Retire le lait », « Ajoute Dune à la liste films » | Sur ton ordinateur |
| **État du PC** | « Le PC est en bonne santé ? » → disque, mémoire, processeur, durée d'allumage, et sous Windows l'état de l'antivirus Defender | Sur ton ordinateur (lecture seule) |
| **Mémoire** | « Retiens que… », « Oublie… » (avec confirmation) | Sur ton ordinateur |
| **Renfort Claude** | Questions difficiles, rédaction, code | Anthropic, uniquement quand il passe la main |

Jarvis **surveille** l'antivirus, il ne le remplace pas : la protection reste
celle de Windows Defender.

## Trouver la configuration la plus rapide (banc d'essai)

Plutôt que de deviner, **mesure** sur ton ordinateur :

```bash
.venv/bin/python bench.py --appliquer          # Mac
.venv\Scripts\python.exe bench.py --appliquer  # Windows
```

Pour chaque modèle (ton modèle actuel + les modèles conseillés déjà installés),
il mesure la vitesse avec la puce graphique puis sur le processeur seul avec
différents nombres de cœurs, le délai avant le premier mot, et vérifie que le
modèle **choisit le bon outil** (heure, mémoire, appel à Claude). Exemple :

```
🧠 qwen3:30b-a3b
   Usage des outils : 5/5
   auto (puce graphique si possible)     18.2 jetons/s, 1er mot  0.6 s, réponse orale ≈  3.6 s → fluide, 100 % sur la puce graphique
   processeur seul, 8 cœurs              11.4 jetons/s, 1er mot  0.9 s, réponse orale ≈  5.7 s → correct
🏆 Meilleure configuration : qwen3:30b-a3b — auto (puce graphique si possible)
```
*(chiffres d'illustration : les tiens dépendront de ta machine)*

Le bon usage des outils passe **avant** la vitesse : un modèle rapide qui se
trompe d'outil est inutilisable. Avec `--appliquer`, il propose d'enregistrer
le gagnant dans `.env` (rien n'est modifié sans ton « oui »). Un rapport complet
est gardé dans `~/.jarvis/bench-*.json`. Pour tester d'autres modèles :
`ollama pull qwen3:14b` puis `bench.py --modeles qwen3:30b-a3b,qwen3:14b`.

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

- Mot de réveil plus robuste au bruit (openWakeWord), et pouvoir interrompre Jarvis quand il parle.
- Idées vues dans d'autres projets Jarvis : recherche web, journal des conversations, dictée dans d'autres applications.
- Démarrage automatique du bot Telegram à l'allumage du Mac.
- Outils Notion (QG « Jarvis — QG » et base « Tâches Jarvis »), agenda, mails, domotique (Home Assistant) :
  ils demandent un compte ou un jeton à toi, on les ajoutera un par un.
- Chaque nouvel outil qui **agit** (envoyer, supprimer, payer, ouvrir) reçoit une confirmation.
