"""Réglages de Jarvis.

Chaque valeur peut être changée avec une variable d'environnement
(par exemple dans le fichier .env, voir .env.example).
"""

import json
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- Cerveau local (Ollama) ---
OLLAMA_HOST = _env("JARVIS_OLLAMA_HOST", "http://localhost:11434")
LOCAL_MODEL = _env("JARVIS_MODELE_LOCAL", "mistral-small3.2")
# Réflexion du modèle local (Qwen3 et autres modèles « qui pensent ») :
# "0" = répond directement (plus rapide, conseillé pour la voix), "1" = réfléchit,
# vide = comportement par défaut du modèle (ne rien envoyer).
_think = _env("JARVIS_REFLEXION_LOCALE", "").strip()
LOCAL_THINK: bool | None = None if _think == "" else _think == "1"


def _json_env(name: str) -> dict:
    raw = _env(name, "").strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[config] {name} n'est pas du JSON valide, ignoré : {raw}")
        return {}
    return value if isinstance(value, dict) else {}


# Réglages fins d'Ollama trouvés par le banc d'essai (bench.py), ex. {"num_thread": 8, "num_gpu": 0}.
LOCAL_OPTIONS: dict = _json_env("JARVIS_OPTIONS_OLLAMA")

# --- Mode 100 % hors ligne ---
# JARVIS_HORS_LIGNE=1 : rien ne sort de l'ordinateur (pas de renfort Claude,
# pas de téléchargement Hugging Face). À activer une fois tout installé.
OFFLINE = _env("JARVIS_HORS_LIGNE", "0") == "1"

# Jamais de statistiques d'utilisation envoyées à Hugging Face.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
if OFFLINE:
    os.environ["HF_HUB_OFFLINE"] = "1"

# --- Renfort Claude ---
# "abonnement" (Claude Code, ton compte Claude) | "api" (clé payante) | "aucun"
RENFORT = "aucun" if OFFLINE else _env("JARVIS_RENFORT", "abonnement").strip().lower()

# Mode "api" : la clé est lue dans ANTHROPIC_API_KEY (jamais écrite dans le code).
CLAUDE_MODEL = _env("JARVIS_MODELE_CLAUDE", "claude-opus-5-5")
CLAUDE_EFFORT = _env("JARVIS_EFFORT_CLAUDE", "medium")  # low | medium | high | xhigh | max

# Mode "abonnement" : modèle choisi dans Claude Code (vide = celui par défaut de ton compte).
CLAUDE_CLI_MODEL = _env("JARVIS_MODELE_ABONNEMENT", "")

# Mode "gemini" : clé sur https://aistudio.google.com (Google AI Studio).
GEMINI_KEY = _env("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = _env("JARVIS_MODELE_GEMINI", "gemini-2.5-flash").strip()
# Mode "gemini-abonnement" : Gemini CLI connecté à ton compte Google (npm install -g @google/gemini-cli).
GEMINI_CLI_ENABLE = _env("JARVIS_GEMINI_ABONNEMENT", "0") == "1"
GEMINI_CLI_MODEL = _env("JARVIS_MODELE_GEMINI_CLI", "").strip()

# --- Mode mentor : Claude exécute des tâches importantes en agent sur le PC ---
# Puissant : Claude peut lire/écrire des fichiers et lancer des commandes, mais
# UNIQUEMENT dans l'atelier ci-dessous, et seulement après ta confirmation.
# "1" pour l'activer. Nécessite Claude Code (mode abonnement).
AGENT = _env("JARVIS_MENTOR", "0") == "1"
WORKSPACE = Path(_env("JARVIS_ATELIER", str(Path.home() / ".jarvis" / "atelier")))
AGENT_MAX_TURNS = int(_env("JARVIS_MENTOR_ETAPES", "30"))

# --- Voix ---
WHISPER_MODEL = _env("JARVIS_WHISPER", "small")  # tiny | base | small | medium | large-v3
PIPER_VOICE = Path(_env(
    "JARVIS_VOIX_PIPER",
    str(Path(__file__).parent / "voix" / "fr_FR-tom-medium.onnx"),
))

# --- Mémoire ---
DATA_DIR = Path(_env("JARVIS_DOSSIER", str(Path.home() / ".jarvis")))
MEMORY_FILE = DATA_DIR / "memoire.json"
REMINDERS_FILE = DATA_DIR / "rappels.json"
LISTS_FILE = DATA_DIR / "listes.json"

# --- Personnalité ---
USER_NAME = _env("JARVIS_PRENOM", "Enes")
TIMEZONE = _env("JARVIS_FUSEAU", "Europe/Paris")
CITY = _env("JARVIS_VILLE", "")  # ville par défaut pour la météo
STYLE = _env("JARVIS_STYLE", "film").strip().lower()  # "film" (majordome) | "ami"
TITLE = _env("JARVIS_TITRE", "").strip()  # ex. Monsieur, Madame, Patron ; vide = prénom

# --- Initiatives de Jarvis ---
# Heure du briefing du matin (HH:MM). Vide = pas de briefing.
BRIEFING_TIME = _env("JARVIS_BRIEFING", "08:00").strip()
# Alertes sur l'état du PC (disque plein, antivirus coupé...). "0" pour les couper.
ALERTS = _env("JARVIS_ALERTES", "1") == "1"
# Heures de silence : ni briefing ni alerte (les rappels, eux, passent toujours).
QUIET_HOURS = _env("JARVIS_SILENCE", "22:00-07:00").strip()
PROACTIVE_FILE = DATA_DIR / "initiatives.json"
# Sentinelle : surveille les signes d'intrusion (nouveaux programmes en écoute, nouveaux
# appareils sur le réseau, pare-feu coupé, menaces Defender...). "0" pour la couper.
SENTINEL = _env("JARVIS_SENTINELLE", "1") == "1"
SENTINEL_FILE = DATA_DIR / "sentinelle.json"

# --- Maison connectée (Home Assistant, local) ---
HA_URL = _env("HOMEASSISTANT_URL", "").strip()      # ex. http://homeassistant.local:8123
HA_TOKEN = _env("HOMEASSISTANT_TOKEN", "").strip()  # jeton d'accès longue durée

# Mode mains libres : secondes d'écoute après une réponse, sans redire « Jarvis ».
AWAKE_SECONDS = float(_env("JARVIS_ECOUTE_SECONDES", "30"))

# Nombre maximum d'allers-retours avec les outils pour une seule question.
MAX_TOOL_ROUNDS = 6
