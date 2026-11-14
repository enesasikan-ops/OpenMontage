# Carte de Jarvis — qui fait quoi

~12 400 lignes de code + ~8 000 lignes de tests (**718 tests**), sur 129 fichiers Python.
Chaque fichier fait **une** chose. Voici comment ils s'assemblent.

## Le flux, en un coup d'œil

```
          TOI
   voix / Telegram / Signal / lunettes
            │
            ▼
   ┌─────────────────┐   questions dures   ┌──────────────────┐
   │  CERVEAU LOCAL  │ ──────────────────▶ │ RENFORT Claude/  │
   │  (Qwen3, Ollama)│ ◀────────────────── │ Gemini           │
   └────────┬────────┘                     └──────────────────┘
            │ choisit un OUTIL        (+ 2ᵉ modèle local consultable)
            ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ Rappels · Maison · Web · Vision · Caméras · Audio · Robot ·  │
   │ Habitudes · Confort · Planificateur · Sécurité · Réseau · …  │
   └─────────────────────────────────────────────────────────────┘
            │
   SÉCURITÉ + RÉSEAU (en fond, tout le temps) ── ALERTES ──▶ TOI
```

**Principe tenu partout :** Jarvis **surveille, propose, alerte** — il n'agit sur le monde
(portail, serrure, pare-feu, code) qu'après confirmation. Il **n'attaque jamais**.

## 🧠 Cerveau & renfort

| Fichier | Rôle |
|---|---|
| `brain.py` | le cerveau local (Ollama) et sa boucle « choisir un outil → agir » |
| `claude_bridge.py` | le renfort Claude/Gemini, avec repli automatique entre les deux |
| `secondmodel.py` | un 2ᵉ modèle local **consultable** (ex. dolphin-llama3) — il répond, n'agit pas |
| `council.py` | planificateur multi-angles (tempête, absence…) : **propose**, n'exécute pas |
| `consolidation.py` | « sommeil cognitif » : range/oublie la mémoire — **proposé**, pas de poids modifiés |
| `routing_eval.py` | banc d'essai : mesure si le cerveau choisit le bon outil (préalable à toute optim.) |
| `config.py` | tous les réglages (lus dans `.env`) |
| `persona.py` | la personnalité, le ton de Jarvis |

## 🗣️ Interfaces

| Fichier | Rôle |
|---|---|
| `main.py` | point d'entrée (clavier ou voix) |
| `voice.py` | oreilles (Whisper) + voix (Piper), 100 % local |
| `handsfree.py` | mode mains libres : dis « Jarvis » |
| `telegram_bot.py` / `signal_bot.py` | Jarvis sur Telegram / Signal (chiffré) |
| `dashboard.py` + `.html` | tableau de bord pour la télé (jeton si exposé) |
| `glasses.py` | lunettes connectées (OpenGlass/Monocle) : tu regardes, tu demandes, réponse sur le verre |

## 🧰 Outils & mémoire

| Fichier | Rôle |
|---|---|
| `tools.py` | catalogue des outils donnés au cerveau |
| `skills.py` | rappels, listes, calcul, météo, état du PC |
| `memory.py` / `people.py` | mémoire à long terme (générale / par personne) |
| `web.py` | recherche et lecture de pages web (anti-SSRF) |
| `pwstrength.py` | robustesse d'un mot de passe / clé Wi-Fi, en local (sans rien attaquer) |

## 🏠 Maison, confort & habitudes

| Fichier | Rôle |
|---|---|
| `smarthome.py` | pilotage Home Assistant (actions sensibles confirmées) |
| `vacuum.py` / `deterrent.py` | aspirateur robot / arroseur anti-nuisibles (dissuasion par zone) |
| `automations.py` | créer des règles HA à la voix (traduites par le renfort, confirmées) |
| `comfort.py` | « mode détente » que **tu** déclenches (lumières douces + musique) |
| `audiofollow.py` | le son te suit de pièce en pièce (Snapcast + présence) |
| `habits.py` | apprend tes routines par comptage **explicable** → **propose** (ne fait pas tout seul) |
| `presence.py` | carte d'occupation anonyme par pièce (PIR / mmWave / Wi-Fi CSI) |

## 👁️ Vision, caméras & robots

| Fichier | Rôle |
|---|---|
| `vision.py` | décrire une image (local d'abord, Gemini en secours) |
| `camera.py` + `ptz.py` | caméras par flux, rotation/presets/ronde (ONVIF) |
| `faces.py` | reconnaissance de visages (locale, tes proches enrôlés) |
| `arrivals.py` + `sightings.py` | annonces d'arrivée (Double Take/CompreFace) + « qui as-tu vu ? » |
| `hearing.py` / `vision_yolo.py` | ouïe analytique (YAMNet) / détection d'objets (YOLO) |
| `drone.py` / `robot.py` | drone (limites de vol) / robot mobile (ROS 2), sur commande |

## 🚨 Sécurité physique (du foyer)

| Fichier | Rôle |
|---|---|
| `poolguard.py` | surveillance piscine : alarme + baies + escalade **annulable** (PAS un détecteur de noyade) |
| `thermal.py` | plaque de cuisson oubliée (caméra thermique MLX90640) |
| `voiceprint.py` | authentification par empreinte **vocale** des actions sensibles (échoue fermé + code de secours) |
| `watchdog.py` | mode Sentinelle (réaction active anti-intrusion, si armé) |

## 🛡️ Cyberdéfense & réseau (en fond, tout le temps)

| Fichier | Rôle |
|---|---|
| `security.py` + `cyberwatch.py` | sentinelle (ports, réseau, pare-feu) + surveillance continue |
| `core_integrity.py` + `defense.py` | tripwire du cœur + preuves + restauration saine |
| `honeypot.py` / `ipblock.py` / `netguard.py` | leurre / blocage d'IP (confirmé) / anti-SSRF |
| `crowdsec.py` | annonce les intrusions réseau bloquées par CrowdSec |
| `vulnscan.py` | audit de posture (ports exposés, firmware périmé) — **détecte, n'exploite pas** |
| `freebox.py` | qui est sur le Wi-Fi via la Freebox, repère les inconnus |
| `wifiwatch.py` | instabilité Wi-Fi = symptôme d'une attaque de déauth (le PMF protège, Jarvis alerte) |
| `radius.py` | lit le journal FreeRADIUS (802.1X) : authentifications rejetées |
| `opnsense.py` | fil d'alarme sur la segmentation VLAN : tentative IoT → cœur bloquée |
| `starlink.py` | surveillance de la liaison Internet (coupure, obstruction) |
| `heartbeat.py` | battement de cœur : détecteur d'homme mort (résilience si le serveur tombe) |

## 🔧 Auto-amélioration & plugins

| Fichier | Rôle |
|---|---|
| `growth.py` | Jarvis progresse (la nuit), toujours avec ta ✅ |
| `plugin_manager.py` | charge/recharge des capacités à chaud |
| `core_proposals.py` | modifier le cœur sur proposition relue (réservé à toi) |
| `scaffold/` | générateur de nouvelles capacités |

## ⚙️ Installation & outillage

| Fichier | Rôle |
|---|---|
| `installer.ps1` / `installer.sh` | tout installer d'un coup |
| `appairer_freebox.py` | appairer Jarvis à la Freebox (une fois) |
| `enroll_voice.py` | enrôler ta voix pour l'auth des actions sensibles |
| `bench.py` | trouver les réglages les plus rapides sur ta machine |
| `installer_embarque.sh` | mini-Jarvis pour le drone |

## 🧪 Tests

`tests/` — **718 tests** (~8 000 lignes). Chaque brique est vérifiée, la sécurité en particulier.

---

Pour la sécurité et les frontières de confiance : voir **SECURITY.md**.
Pour les règles de modification du cœur : voir **CLAUDE.md**.
