# Carte de Jarvis — qui fait quoi

~6 900 lignes de code + ~4 560 lignes de tests (387 tests), sur 63 fichiers Python.
Chaque fichier fait **une** chose. Voici comment ils s'assemblent.

## Le flux, en un coup d'œil

```
          TOI
   voix / Telegram / Signal
            │
            ▼
   ┌─────────────────┐     questions dures     ┌──────────────────┐
   │  CERVEAU LOCAL  │ ──────────────────────▶ │ RENFORT Claude/  │
   │  (Qwen3, Ollama)│ ◀────────────────────── │ Gemini           │
   └────────┬────────┘                          └──────────────────┘
            │ choisit un OUTIL
            ▼
   ┌─────────────────────────────────────────────────────────┐
   │ Rappels · Maison · Web · Drone · Vision · Caméras · …    │
   └─────────────────────────────────────────────────────────┘
            │
   SÉCURITÉ (en fond, tout le temps) ── ALERTES ──▶ TOI
```

## 🧠 Cerveau & renfort

| Fichier | Lignes | Rôle |
|---|---|---|
| `brain.py` | 138 | le cerveau local (Ollama) et sa boucle « choisir un outil → agir » |
| `claude_bridge.py` | 607 | le renfort Claude/Gemini, avec le repli automatique entre les deux |
| `config.py` | 202 | tous les réglages (lus dans `.env`) |
| `persona.py` | 108 | la personnalité, le ton de Jarvis |

## 🗣️ Interfaces (comment tu lui parles)

| Fichier | Lignes | Rôle |
|---|---|---|
| `main.py` | 250 | point d'entrée (clavier ou voix) |
| `voice.py` | 132 | oreilles (Whisper) + voix (Piper), 100 % local |
| `handsfree.py` | 183 | mode mains libres : dis « Jarvis » |
| `telegram_bot.py` | 405 | Jarvis sur Telegram (texte + vocal) |
| `signal_bot.py` | 451 | Jarvis sur Signal (chiffré, deux sens) |
| `signal_notify.py` | 89 | alertes Signal (envoi seul) |
| `dashboard.py` + `.html` | 226 | tableau de bord pour la télé |

## 🧰 Outils & capacités

| Fichier | Lignes | Rôle |
|---|---|---|
| `tools.py` | 186 | catalogue des outils donnés au cerveau |
| `skills.py` | 497 | rappels, listes, calcul, météo, état du PC |
| `memory.py` | 56 | mémoire à long terme |
| `web.py` | 114 | recherche et lecture de pages web |
| `smarthome.py` | 273 | pilotage de la maison (Home Assistant) |

## 👁️ Vision & drone

| Fichier | Lignes | Rôle |
|---|---|---|
| `vision.py` | 92 | décrire une image |
| `camera.py` | 145 | caméras par flux |
| `faces.py` | 195 | reconnaissance de visages (locale, tes proches) |
| `drone.py` | 446 | pilotage + vision du drone, avec limites de vol |

## 🔧 Auto-amélioration & plugins

| Fichier | Lignes | Rôle |
|---|---|---|
| `growth.py` | 379 | Jarvis progresse (la nuit), toujours avec ta ✅ |
| `plugin_manager.py` | 378 | charge/recharge des capacités à chaud |
| `core_proposals.py` | 116 | modifier le cœur sur proposition relue (réservé à toi) |
| `scaffold/` | ~690 | générateur de nouvelles capacités |

## 🛡️ Cyberdéfense (en fond, tout le temps)

| Fichier | Lignes | Rôle |
|---|---|---|
| `security.py` | 239 | sentinelle : ports, réseau, pare-feu, comptes |
| `cyberwatch.py` | 111 | surveillance continue (machine + cœur) |
| `core_integrity.py` | 74 | tripwire : alerte si le code du cœur change |
| `defense.py` | 71 | preuves + restauration du cœur sain |
| `honeypot.py` | 116 | faux serveur leurre pour piéger les intrus |
| `ipblock.py` | 95 | blocage d'IP défensif (sur ta décision) |
| `netguard.py` | 53 | anti-SSRF (bloque les adresses internes) |
| `proactive.py` | 169 | initiatives : Jarvis parle en premier quand c'est utile |

## ⚙️ Installation & outillage

| Fichier | Rôle |
|---|---|
| `installer.ps1` / `installer.sh` | tout installer d'un coup (Windows / macOS-Linux) |
| `optimiser_windows.ps1` | régler le PC pour Jarvis |
| `bench.py` | trouver les réglages les plus rapides sur ta machine |
| `installer_embarque.sh` | mini-Jarvis pour le drone |

## 🧪 Tests

`tests/` — 387 tests (~4 560 lignes). Chaque brique est vérifiée, la sécurité en particulier.

---

Pour la sécurité et les frontières de confiance : voir **SECURITY.md**.
Pour les règles de modification du cœur : voir **CLAUDE.md**.
