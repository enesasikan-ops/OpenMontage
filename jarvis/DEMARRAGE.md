# Démarrage de Jarvis — comment ça marche, et comment le lancer

## Comment ça marche (en clair)

Jarvis tient sur **un seul ordinateur** (le mini PC), chez vous. Tout est local.

```
         VOUS
   voix · Telegram · Signal
            │
            ▼
   ┌──────────────────┐   question difficile   ┌──────────────────┐
   │  CERVEAU LOCAL   │ ────────────────────▶  │ RENFORT          │
   │  Qwen3 (Ollama)  │ ◀────────────────────  │ Claude / Gemini  │
   └────────┬─────────┘                         └──────────────────┘
            │  choisit un OUTIL
            ▼
   maison · caméras · drone · aspirateur · mémoire · agenda · sécurité
            │
   Il agit, puis vous répond — à voix haute ou par message.
```

- **Vous parlez** (micro, ou depuis le téléphone via Telegram/Signal).
- **Whisper** transforme votre voix en texte.
- **Le cerveau local (Qwen3)** comprend, et **choisit l'outil** qu'il faut (allumer une lumière, regarder une caméra, lancer l'aspirateur…). Pour une question dure, il appelle **Claude/Gemini**.
- **Piper** lit la réponse à voix haute, dans le style majordome.
- En fond, la **sécurité** veille en permanence (machine, caméras, intégrité de son propre code).

Rien ne sort de chez vous, sauf quand il appelle le renfort — et vous pouvez même couper ça (mode hors ligne).

## Ce qu'il vous faut

1. **Le mini PC** (le GMKtec 64 Go convient très bien).
2. Un **micro** et un **haut-parleur** (ou une enceinte), si vous lui parlez à la voix.
3. Internet (seulement pour le renfort Claude/Gemini ; sinon tout marche en local).
4. En option : caméras Reolink, Home Assistant, drone, aspirateur Valetudo.

## Les étapes, dans l'ordre

### 1. Installer Jarvis (automatique)
Sur le mini PC (Windows), dans PowerShell, depuis le dossier `jarvis` :
```
powershell -ExecutionPolicy Bypass -File .\installer.ps1
```
Ça installe tout seul : Python, Ollama, le modèle Qwen3, la voix, Whisper. Patientez (le modèle fait plusieurs Go).

### 2. Régler les secrets
Copiez `.env.example` en `.env`, puis remplissez ce que vous utilisez :
- **Telegram** : `TELEGRAM_TOKEN` (donné par @BotFather) — pour parler depuis le téléphone.
- **Renfort Claude** : installez Claude Code et lancez `claude` une fois pour vous connecter (gratuit avec votre abonnement).
- Le reste (`JARVIS_TITRE=Monsieur`, voix, etc.) selon votre goût.

### 3. Lancer Jarvis
```
.venv\Scripts\python.exe main.py                 # au clavier
.venv\Scripts\python.exe main.py --mains-libres  # à la voix : dites « Jarvis »
.venv\Scripts\python.exe telegram_bot.py         # depuis le téléphone
.venv\Scripts\python.exe signal_bot.py           # idem, en plus privé
```

### 4. (Plus tard) Brancher la maison
- **Home Assistant** : mettez son adresse et un jeton dans `.env` → lumières, serrures, aspirateur, agenda.
- **Caméras Reolink** : adresses RTSP dans `cameras.json` (+ `ptz.json` pour les motorisées).
- **Arrivées** : Frigate + Double Take + un broker MQTT (Mosquitto) → Jarvis annonce qui arrive.
- **Aspirateur** : Valetudo → l'aspirateur apparaît dans Home Assistant.

## Comment lui parler

- « Jarvis, quelle heure est-il ? »
- « Allume le salon. » / « Verrouille la porte. »
- « Aspire la cuisine. »
- « Qu'est-ce que tu vois à l'entrée ? » / « Fais le tour du jardin. »
- « Retiens que Carlos aime le café sans sucre. »
- « Quand je dis bonne nuit, éteins tout et verrouille. »
- « Arme la surveillance. » (mode Sentinelle)

Jarvis demande toujours **confirmation** pour une action sensible, et rien de durable (code, automatisations) n'est appliqué sans votre accord.

## En cas de souci

- La voix ne marche pas → relancez l'installeur (il télécharge Piper et Whisper).
- Le cerveau est lent → mettez un modèle plus léger : `JARVIS_MODELE_LOCAL=qwen3:14b`.
- Pas de renfort → vérifiez que `claude` est connecté, ou mettez une clé Gemini.

Pour la carte des fichiers, voir **CARTE.md**. Pour la sécurité, **SECURITY.md**.
