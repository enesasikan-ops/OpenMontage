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
| `api` | Passe par une clé API Anthropic (`ANTHROPIC_API_KEY`) | Environ 3 centimes par question difficile (Claude Opus 5.5) |
| `gemini` | Gemini (Google) via une clé API (`GEMINI_API_KEY`) | Payé à l'usage (offre gratuite disponible) |
| `gemini-abonnement` | Gemini via **Gemini CLI**, connecté à ton compte Google | Inclus dans ton abonnement Google |
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

**Mode Gemini** : crée une clé sur <https://aistudio.google.com> (Google AI Studio),
colle-la après `GEMINI_API_KEY=` et mets `JARVIS_RENFORT=gemini`. Le modèle se règle
avec `JARVIS_MODELE_GEMINI` (défaut `gemini-2.5-flash`). Gemini peut **répondre**,
mais pas **agir** sur l'ordinateur : le mode mentor (exécuter des tâches) reste réservé
à Claude Code.

**Claude ET Gemini ensemble** : garde `JARVIS_RENFORT=abonnement` (Claude en principal,
y compris pour agir et coder) et renseigne aussi `GEMINI_API_KEY`. Jarvis gagne alors un
outil « demander à Gemini » : tu peux dire « demande à Gemini ce qu'il en pense » pour
un deuxième avis, pendant que Claude reste le renfort principal.

**Abonnement Gemini (Gemini CLI)** : comme Claude Code pour Claude, Gemini CLI se connecte
à ton compte Google (pas de clé, pas de coût en plus).
```bash
npm install -g @google/gemini-cli
gemini          # connecte-toi à ton compte Google, puis quitte
```
Puis, dans `.env`, soit `JARVIS_RENFORT=gemini-abonnement` (Gemini en principal), soit
`JARVIS_GEMINI_ABONNEMENT=1` avec `JARVIS_RENFORT=abonnement` pour avoir **Claude ET
l'abonnement Gemini** : Claude agit et code, Gemini donne un deuxième avis. Si une clé API
Gemini est aussi présente, c'est elle qui sert pour le deuxième avis.

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
| **Maison connectée** | « Allume le salon », « ferme le garage » (confirmation), « température du salon » | Sur ton réseau local (Home Assistant) |
| **Web** | « Cherche les horaires du train », « lis cette page » | DuckDuckGo (nom de la recherche seulement) |
| **Drone** | « Fais décoller », « avance de 3 m », « qu'est-ce que tu vois ? », « atterris » | Parrot ANAFI (local) + vision Gemini/Claude |
| **Mentor (code)** | « Écris-moi un script qui… » → Claude l'exécute dans l'atelier (confirmation) | Ton abonnement Claude |
| **Sécurité** | « Rapport de sécurité », « Lance une analyse antivirus » (avec confirmation) | Sur ton ordinateur |
| **État du PC** | « Le PC est en bonne santé ? » → disque, mémoire, processeur, durée d'allumage, et sous Windows l'état de l'antivirus Defender | Sur ton ordinateur (lecture seule) |
| **Mémoire** | « Retiens que… », « Oublie… » (avec confirmation) | Sur ton ordinateur |
| **Renfort Claude** | Questions difficiles, rédaction, code | Anthropic, uniquement quand il passe la main |

Jarvis **surveille** l'antivirus, il ne le remplace pas : la protection reste
celle de Windows Defender.

## Les initiatives de Jarvis (il parle en premier)

| Initiative | Quand | Réglage dans `.env` |
|---|---|---|
| **Briefing du matin** : météo, rappels du jour, liste de courses, état du PC | À l'heure choisie. Si le PC était éteint, il le donne à l'allumage dans les 3 heures, sinon il le saute. | `JARVIS_BRIEFING=08:00` (vide = jamais). La météo demande `JARVIS_VILLE`. |
| **Alertes** : disque presque plein, antivirus désactivé ou pas à jour, redémarrage conseillé | Vérifié toutes les heures ; chaque problème est signalé une fois par jour au plus. | `JARVIS_ALERTES=1` (0 = aucune) |
| **Rappels** | À l'heure demandée, toujours. | — |
| **Heures de silence** | Ni briefing ni alerte la nuit. | `JARVIS_SILENCE=22:00-07:00` |

Les messages arrivent là où Jarvis tourne : à voix haute en mode vocal, sur
Telegram si le bot est lancé. Si les deux tournent, le briefing n'est donné
qu'une fois. Jarvis ne fait que **prévenir** : il ne corrige rien tout seul.

## Piloter la maison connectée

Jarvis commande tes objets connectés par l'intermédiaire de **Home Assistant**,
le logiciel domotique libre et gratuit (il tourne en local, souvent sur le même
mini-PC). Home Assistant a déjà fait le travail d'intégration de milliers
d'appareils de toutes marques : une fois tes objets ajoutés dans Home Assistant,
Jarvis les pilote, quels qu'ils soient.

Exemples :
- « Jarvis, allume le salon », « éteins tout »
- « Mets la lumière de la chambre à 30 % »
- « Ouvre le volet du salon », « ferme le garage » *(confirmation demandée)*
- « Verrouille la porte d'entrée » *(confirmation demandée)*
- « Lance l'ambiance cinéma »
- « Qu'est-ce qui est allumé ? », « la porte du garage est fermée ? », « température du salon »

Mise en place :
1. Installe **Home Assistant** (home-assistant.io) et ajoutes-y tes objets connectés.
2. Dans Home Assistant : ton profil → en bas, **Jetons d'accès longue durée** → crée un jeton.
3. Dans `.env` : `HOMEASSISTANT_URL=http://homeassistant.local:8123` et `HOMEASSISTANT_TOKEN=<ton jeton>`.

À savoir :
- Tout reste **sur ton réseau local** : la domotique marche même en mode 100 % hors ligne.
- Les actions sensibles (serrures, volets, portail, garage) demandent ta confirmation.
- Si tu dis « allume le salon » et que plusieurs lampes correspondent, il les allume toutes.
- Le jeton donne le contrôle de ta maison : garde-le comme un mot de passe.

## Piloter un drone (Parrot ANAFI) et voir à travers

Jarvis peut piloter un **Parrot ANAFI** à la voix et décrire ce que voit sa caméra.

Exemples :
- « Jarvis, fais décoller le drone » *(confirmation demandée)*
- « Avance de 3 mètres », « tourne à droite », « monte d'un mètre »
- « Qu'est-ce que tu vois ? » → il analyse l'image du drone et te décrit la scène
- « Atterris », « Arrête-toi » / « Stop » → **toujours prioritaires**, sans confirmation
- « Quel est l'état du drone ? » → en vol/au sol, batterie, altitude

Réglages dans `.env` :
- `JARVIS_DRONE=sim` : **simulateur**, pour tester sans matériel (le drone « vole » pour de faux).
- `JARVIS_DRONE=mavlink` : **drone DIY** (ArduPilot/PX4) via MAVLink, pour un mini-Jarvis
  **embarqué** sur le drone. Montage, matériel et test en simulateur : voir
  [DRONE_DIY.md](DRONE_DIY.md). Testable sans matériel dans le simulateur ArduPilot SITL.
- `JARVIS_DRONE=anafi` : le vrai drone, via le **SDK officiel Parrot Olympe** (Linux) :
  `pip install parrot-olympe`, le PC connecté au Wi-Fi du drone.
  Le même mode marche avec **Parrot Sphinx**, le simulateur officiel de Parrot : lance
  Sphinx, puis mets `JARVIS_DRONE=anafi` et `JARVIS_DRONE_IP` sur l'adresse du drone
  simulé. Le vrai code de vol est ainsi testé de façon réaliste, sans matériel ni risque.
  (Olympe et Sphinx sont les outils officiels de Parrot — c'est la base retenue ici.)
- `JARVIS_DRONE_IP` : l'adresse du drone (par défaut `192.168.42.1`).
- La **vision** (« qu'est-ce que tu vois ? ») : voir ci-dessous.

## Reconnaissance de visages (locale)

Donne une photo à Jarvis — « voici une photo de moi » — et il te reconnaîtra ensuite
sur la caméra ou la vue du drone.

- « Jarvis, retiens mon visage, voici une photo : /chemin/photo.jpg » *(confirmation demandée)*
- « Qui est là ? », « tu me reconnais ? » → il regarde et dit qui il reconnaît
- « Qui connais-tu ? », « oublie le visage de X »

Vie privée :
- **Tout reste sur l'ordinateur** : un fichier de signatures (pas les photos), rien sur internet.
- Ça ne sert qu'à reconnaître les personnes **que tu enregistres, avec leur accord** — pas à
  identifier des inconnus ni à surveiller. Enregistrer un visage demande confirmation.
- Active-la avec `JARVIS_VISAGES=1`. Elle a besoin de `face-recognition` et `pillow` :
  `pip install face-recognition pillow` (c'est un peu long à installer, surtout sur un petit PC).

### La vision de Jarvis

« Qu'est-ce que tu vois ? » (sur la vue du drone) passe par un modèle qui lit les images.
Deux voies, réglées avec `JARVIS_VISION` :

| Mode | Qui voit | Vie privée |
|---|---|---|
| `local` *(préféré)* | Un modèle **sur le mini-PC** via Ollama | ✅ Rien ne sort de l'ordinateur, marche hors ligne |
| `gemini` | Gemini (Google) | ❌ L'image part chez Google |
| `auto` *(défaut)* | Local si réglé, sinon Gemini | — |

Pour la vision **locale** : `ollama pull qwen2.5-vl` (ou `llama3.2-vision`, `moondream`
pour les petites configs), puis `JARVIS_MODELE_VISION=qwen2.5-vl` dans `.env`.
Cette même vision servira aussi, plus tard, pour décrire une capture d'écran ou une photo.

Sécurité, toujours :
- Confirmation avant le décollage ; « atterris » et « stop » passent en priorité.
- **Simulateur** (`JARVIS_DRONE=sim`) : aucune limite ni confirmation, c'est virtuel.
- **Vrai vol** : sous la **limite normale** (légale, 120 m / 400 ft par défaut), le drone
  vole librement. **Au-dessus**, Jarvis demande d'abord « c'est au-dessus de votre limite,
  vous êtes sûr ? » et, si tu confirmes, va jusqu'au **plafond absolu** (500 m par défaut).
  Réglages : `JARVIS_DRONE_ALT_MAX` (limite normale), `JARVIS_DRONE_ALT_PLAFOND` (plafond),
  idem pour l'éloignement (`..._DIST_...`). À toi de rester légal — tu es responsable.
- Jarvis **exécute tes ordres**, il ne vole pas en autonomie (pas de « suis cette personne »
  tout seul) : analyser une image prend 1 à 3 s, trop lent pour éviter un obstacle en vol.
- **Garde le drone à vue** et respecte les règles (pas au-dessus des gens, pas en zone interdite).

## Naviguer sur le web et déléguer à Claude

**Recherche web** (locale, via DuckDuckGo, sans clé) :
- « Jarvis, cherche les horaires du train Paris–Lyon », « c'est quoi la météo de demain à Rome ? »
- « Lis-moi cette page : exemple.fr/article »

Désactivée en mode hors ligne.

**Mode mentor — Claude exécute les tâches importantes** *(optionnel, `JARVIS_MENTOR=1`)*

Quand tu demandes un vrai travail — « écris-moi un script qui range mes photos »,
« crée un programme qui… » — Jarvis me le **confie**, et je l'exécute vraiment sur
l'ordinateur, comme un agent, puis je te rends un résumé à voix haute.

- Je travaille **uniquement dans l'atelier** `~/.jarvis/atelier` (`--add-dir`), pas ailleurs sur le PC.
- Jarvis demande **ta confirmation** avant de me confier quoi que ce soit.
- J'utilise ton **abonnement** Claude (Claude Code), pas de coût en plus.
- C'est **puissant** : je peux écrire des fichiers et lancer des commandes dans l'atelier.
  À n'activer que si tu comprends ce que ça permet. Par défaut, c'est désactivé.
- Réglages : `JARVIS_ATELIER` (le dossier de travail), `JARVIS_MENTOR_ETAPES` (nombre d'étapes max).

Ainsi Jarvis fait lui-même le simple et le quotidien, et pour le compliqué il
s'appuie sur moi — exactement comme tu l'as demandé.

## Le tableau de bord sur la télé

Jarvis peut afficher un écran plein écran (façon film) avec tes vraies données,
mises à jour en direct : heure, météo, rappels du jour, maison connectée,
sécurité, état du PC.

```bash
.venv/bin/python dashboard.py            # Mac/Linux
.venv\Scripts\python.exe dashboard.py   # Windows
```

Puis ouvre **http://localhost:8765** dans le navigateur, en plein écran (touche F11).
Branche le mini-PC sur la télé en HDMI : la télé devient ton écran Jarvis.

**Démarrage automatique (Windows)** : le script `optimiser_windows.ps1` propose de lancer
le tableau de bord à l'allumage, et même de l'afficher en **plein écran** sur la télé
(mode kiosque, via Edge). Rien à faire à la main ensuite.

**Démarrage automatique (Mac)** : le plus simple est d'ajouter, dans Réglages Système →
Général → Ouverture, un petit script `.command` qui lance `dashboard.py`, puis d'ouvrir
http://localhost:8765 en plein écran.

- Par défaut, l'écran n'est visible que **sur ce PC** (`JARVIS_ECRAN_HOTE=127.0.0.1`).
- Pour l'afficher depuis une **tablette** sur ton réseau, mets `JARVIS_ECRAN_HOTE=0.0.0.0`
  et ouvre `http://<adresse-du-PC>:8765`. Ne fais ça que sur un réseau de confiance :
  la page montre tes données à qui est sur le réseau (il n'y a pas de mot de passe).
- La météo se met à jour toutes les 15 min, la sécurité toutes les 2 min, le reste en continu.
- Tout reste **en local** : la page ne parle qu'à ton ordinateur.

## La sentinelle (sécurité)

Jarvis **ne remplace ni l'antivirus ni le pare-feu** et ne bloque aucune attaque :
c'est le travail de Windows Defender. Il joue le rôle du veilleur : il mémorise
l'état normal de la machine, puis vérifie toutes les 5 minutes ce qui a changé.

| Ce qu'il remarque | Gravité | Quand il le dit |
|---|---|---|
| Menace détectée par Windows Defender | Critique | Tout de suite, même la nuit |
| Nouveau compte administrateur | Critique | Tout de suite, même la nuit |
| Pare-feu Windows désactivé | Critique | Tout de suite, même la nuit |
| Nouveau programme qui accepte des connexions venant du réseau | Information | Tout de suite, ou au matin si c'est la nuit |
| Nouveau programme lancé au démarrage | Information | Idem |
| Appareil inconnu sur le réseau local | Information | Idem |

À la demande : « Jarvis, rapport de sécurité », « sommes-nous en sécurité ? »,
« lance une analyse antivirus » (après ta confirmation).

Limites à connaître :
- Au premier lancement, il mémorise l'état actuel **comme normal** : si la machine
  est déjà compromise, il ne le verra pas. Installe-le sur un PC sain.
- Chaque nouveauté est signalée une fois. Beaucoup seront légitimes (un logiciel
  que tu viens d'installer, le téléphone d'un invité) : c'est à toi de juger.
- Il ne voit que les appareils avec lesquels le PC a déjà échangé, pas tout le réseau.
- Un pirate qui a pris le contrôle du PC peut aussi arrêter Jarvis.
- Pare-feu, menaces, comptes et démarrage ne sont surveillés que sous Windows.
- Tout est en lecture seule et reste sur l'ordinateur. `JARVIS_SENTINELLE=0` la coupe.

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
- Démarrage automatique du bot Telegram et du tableau de bord à l'allumage.
- Outils Notion (QG « Jarvis — QG » et base « Tâches Jarvis »), agenda, mails, mails :
  ils demandent un compte ou un jeton à toi, on les ajoutera un par un.
- Chaque nouvel outil qui **agit** (envoyer, supprimer, payer, ouvrir) reçoit une confirmation.
