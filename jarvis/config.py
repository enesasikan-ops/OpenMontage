"""Réglages de Jarvis.

Chaque valeur peut être changée avec une variable d'environnement
(par exemple dans le fichier .env, voir .env.example).
"""

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# --- Cerveau local (Ollama) ---
OLLAMA_HOST = _env("JARVIS_OLLAMA_HOST", "http://localhost:11434")
LOCAL_MODEL = _env("JARVIS_MODELE_LOCAL", "mistral-small3.2")

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

# --- Voix ---
WHISPER_MODEL = _env("JARVIS_WHISPER", "small")  # tiny | base | small | medium | large-v3
PIPER_VOICE = Path(_env(
    "JARVIS_VOIX_PIPER",
    str(Path(__file__).parent / "voix" / "fr_FR-siwis-medium.onnx"),
))

# --- Mémoire ---
DATA_DIR = Path(_env("JARVIS_DOSSIER", str(Path.home() / ".jarvis")))
MEMORY_FILE = DATA_DIR / "memoire.json"

# --- Personnalité ---
USER_NAME = _env("JARVIS_PRENOM", "Enes")
TIMEZONE = _env("JARVIS_FUSEAU", "Europe/Paris")

# Nombre maximum d'allers-retours avec les outils pour une seule question.
MAX_TOOL_ROUNDS = 6
