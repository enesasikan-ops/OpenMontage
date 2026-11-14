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
# Qwen3-30B-A3B : modèle « mixture of experts » (30B au total, 3B actifs par mot) : malin
# comme un gros, rapide comme un petit — idéal sur un mini PC sans GPU dédié. Le code dur
# part de toute façon au renfort (Claude/Gemini). Alternative plus fine mais plus lente : qwen3:32b.
LOCAL_MODEL = _env("JARVIS_MODELE_LOCAL", "qwen3:30b-a3b")
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

# --- Repli du renfort : qui code si le principal ne peut pas (quota, non connecté, panne) ---
# Le principal est choisi par JARVIS_RENFORT ci-dessus ; ce réglage choisit le remplaçant.
#   "auto"       : l'AUTRE famille que le principal (Claude devant → Gemini en repli,
#                  Gemini devant → Claude en repli), s'il est installé. Défaut.
#   "gemini-cli" / "gemini" : forcer un repli Gemini (quand le principal est Claude) ;
#   "claude" / "claude-api" : forcer un repli Claude (quand le principal est Gemini) ;
#   "aucun"      : pas de repli.
# Un repli n'est retenu que s'il est réellement disponible, et jamais vers la même famille.
RENFORT_REPLI = _env("JARVIS_RENFORT_REPLI", "auto").strip().lower()

# --- Cybersurveillance continue (cyberwatch.py) ---
# Jarvis surveille en permanence la machine (ports, réseau, pare-feu…) ET son propre
# code (tripwire d'intégrité du cœur). 1 = activé (défaut).
CYBERWATCH = _env("JARVIS_CYBERSURVEILLANCE", "1") == "1"
CYBERWATCH_INTERVAL = float(_env("JARVIS_CYBERSURVEILLANCE_SECONDES", "300"))
# Réaction automatique : si un fichier du cœur est trafiqué, Jarvis le RESTAURE tout seul
# (sûr et réversible : il remet une version saine, il ne génère pas de code). 1 = activé.
# NB : si tu modifies le cœur hors du bot, fais « sauvegarde cœur » après, sinon la réaction
# auto remettra ton changement à l'état d'avant. L'application de code généré reste, elle,
# toujours soumise à ta validation.
AUTO_RESTORE = _env("JARVIS_AUTO_RESTAURATION", "0") == "1"

# --- Ouïe analytique (classification des sons, hearing.py) ---
# Un micro + YAMNet : Jarvis entend bris de glace, alarme incendie, pleurs… 1 = activé.
OREILLE = _env("JARVIS_OREILLE", "0") == "1"
OREILLE_SEUIL = float(_env("JARVIS_OREILLE_SEUIL", "0.5"))

# --- Pot de miel (honeypot.py) ---
# Un faux serveur leurre : toute connexion est suspecte, Jarvis note l'IP et t'alerte.
# N'a aucun accès au cœur (pièce la plus exposée = la moins privilégiée). 0 = coupé.
# Port > 1024 pour éviter les droits root. Expose-le au réseau/internet en connaissance de cause.
HONEYPOT = _env("JARVIS_HONEYPOT", "0") == "1"
HONEYPOT_PORT = int(_env("JARVIS_HONEYPOT_PORT", "2222"))

# Blocage d'IP (riposte défensive, sur ta décision). Liste blanche d'IP publiques à ne
# JAMAIS bloquer (DNS, services que tu utilises), séparées par des virgules. Les IP
# internes/privées sont déjà protégées d'office.
IP_LISTE_BLANCHE = tuple(x.strip() for x in _env("JARVIS_IP_LISTE_BLANCHE", "").split(",") if x.strip())

# --- Annonces d'arrivée (caméras Frigate / Double Take via MQTT) ---
# Jarvis annonce « Monsieur, Carlos est à la porte » / alerte sur un inconnu. 0 = coupé.
MQTT = _env("JARVIS_MQTT", "0") == "1"
MQTT_HOST = _env("JARVIS_MQTT_HOTE", "localhost")
MQTT_PORT = int(_env("JARVIS_MQTT_PORT", "1883"))
MQTT_TOPIC = _env("JARVIS_MQTT_SUJET", "double-take/matches/#")
MQTT_USER = _env("JARVIS_MQTT_USER", "")
MQTT_PASS = _env("JARVIS_MQTT_PASS", "")
# Auto-regard : sur détection, Jarvis oriente une caméra motorisée vers la zone et décrit.
# Sans danger (bouger une caméra est réversible), donc autonome. 1 = activé.
AUTO_REGARD = _env("JARVIS_AUTO_REGARD", "1") == "1"

# --- Mode Sentinelle (réaction active anti-intrusion, watchdog.py) ---
# Armé par toi ; sur visage inconnu, Jarvis allume/verrouille/enregistre/avertit + t'alerte.
# (SURV_FILE est défini plus bas, après DATA_DIR.)


def _liste(name: str) -> tuple:
    return tuple(x.strip() for x in _env(name, "").split(",") if x.strip())


def surv_settings() -> dict:
    return {
        "lumieres": list(_liste("JARVIS_SURV_LUMIERES")),      # entity_id des lumières extérieures
        "serrures": list(_liste("JARVIS_SURV_SERRURES")),      # entity_id des serrures
        "verrouiller": _env("JARVIS_SURV_VERROUILLER", "0") == "1",
        "haut_parleur": _env("JARVIS_SURV_HAUTPARLEUR", "").strip(),  # media_player extérieur
        "message": _env("JARVIS_SURV_MESSAGE", "").strip(),     # vide = message dissuasif par défaut
        "tts_service": _env("JARVIS_SURV_TTS", "tts.google_translate_say").strip(),
        "enregistrement_service": _env("JARVIS_SURV_ENR_SERVICE", "").strip(),  # ex. switch.turn_on
        "enregistrement_entite": _env("JARVIS_SURV_ENR_ENTITE", "").strip(),
    }

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
# Prosodie : rendre la voix plus humaine (pose, pauses pour respirer, expressivité).
# vitesse > 1 = plus posé ; pauses = silence entre phrases ; expressivité = variation d'intonation.
PIPER_VITESSE = float(_env("JARVIS_VOIX_VITESSE", "1.06"))      # length_scale
PIPER_PAUSES = float(_env("JARVIS_VOIX_PAUSES", "0.35"))        # sentence_silence (secondes)
PIPER_EXPRESSIVITE = float(_env("JARVIS_VOIX_EXPRESSIVITE", "0.7"))  # noise_scale (0.3 = sobre, 1 = ample)

# --- Mémoire ---
DATA_DIR = Path(_env("JARVIS_DOSSIER", str(Path.home() / ".jarvis")))
MEMORY_FILE = DATA_DIR / "memoire.json"
PEOPLE_FILE = DATA_DIR / "personnes.json"   # mémoire par personne (goûts, relations…)
SURV_FILE = DATA_DIR / "sentinelle_active.json"   # état armé/désarmé du mode Sentinelle
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

# --- Reconnaissance de visages (locale, pour les gens que TU enregistres) ---
FACES = _env("JARVIS_VISAGES", "0") == "1"
FACES_FILE = DATA_DIR / "visages.json"

# --- Caméras par adresse de flux (publiques ou à toi) ---
CAMERAS_FILE = DATA_DIR / "cameras.json"
# Caméras motorisées (PTZ) : { "jardin": {"host","port","user","pass","presets":{"portail":"1"}} }.
# Les « presets » (nom -> numéro ONVIF) activent la ronde (« fais le tour »). Accès locaux.
PTZ_FILE = DATA_DIR / "ptz.json"

# --- Journal des améliorations (ce que Jarvis ne sait pas encore faire) ---
GROWTH_FILE = DATA_DIR / "ameliorations.json"
# Amélioration de nuit (mode mentor requis) : heure à laquelle le mentor code l'idée la
# plus demandée. Vide = désactivé. Tu valides le matin avant activation.
IMPROVE_AT = _env("JARVIS_AMELIORATION_NUIT", "03:00").strip()

# Rechargement à chaud des extensions (plugins/) : sans redémarrer Jarvis.
PLUGINS_HOT = _env("JARVIS_RECHARGEMENT_A_CHAUD", "1") == "1"
PLUGINS_INTERVAL = float(_env("JARVIS_RECHARGEMENT_SECONDES", "2"))

# --- Drone (Parrot ANAFI) ---
# "0" = pas de drone, "sim" = simulateur (démo sans matériel), "anafi" = vrai drone.
DRONE = _env("JARVIS_DRONE", "0").strip().lower()
DRONE_IP = _env("JARVIS_DRONE_IP", "192.168.42.1").strip()  # IP du Parrot ANAFI en Wi-Fi direct
# Drone DIY (ArduPilot/PX4) via MAVLink. udp:127.0.0.1:14550 = simulateur ArduPilot SITL.
DRONE_URL = _env("JARVIS_DRONE_URL", "udp:127.0.0.1:14550").strip()
# Limites de vol. En dessous de la limite « normale » (légale), le drone vole librement.
# Au-dessus — mais sous le PLAFOND absolu — Jarvis demande d'abord « vous êtes sûr ? ».
# Défauts : limite légale 120 m / 120 m d'éloignement ; plafond absolu 500 m (modèle DJI).
DRONE_ALT_MAX = float(_env("JARVIS_DRONE_ALT_MAX", "120"))        # limite normale (légale), altitude
DRONE_ALT_CEILING = float(_env("JARVIS_DRONE_ALT_PLAFOND", "500"))  # plafond absolu, altitude
DRONE_DIST_MAX = float(_env("JARVIS_DRONE_DIST_MAX", "120"))      # limite normale, éloignement
DRONE_DIST_CEILING = float(_env("JARVIS_DRONE_DIST_PLAFOND", "2000"))  # plafond absolu, éloignement
DRONE_STEP_MAX = float(_env("JARVIS_DRONE_PAS_MAX", "20"))        # déplacement max par commande

# --- Vision (décrire une image : vue du drone, capture...) ---
# "auto" (local si dispo, sinon Gemini), "local", "gemini", ou "0" pour couper.
VISION = _env("JARVIS_VISION", "auto").strip().lower()
# Modèle de vision local via Ollama (ex. qwen2.5-vl, llama3.2-vision, moondream). Vide = pas de vision locale.
VISION_MODEL = _env("JARVIS_MODELE_VISION", "").strip()

# --- Tableau de bord (écran/télé) ---
# localhost = visible seulement sur ce PC. 0.0.0.0 = visible depuis le réseau (tablette...).
DASHBOARD_HOST = _env("JARVIS_ECRAN_HOTE", "127.0.0.1").strip()
DASHBOARD_PORT = int(_env("JARVIS_ECRAN_PORT", "8765"))
# Jeton d'accès au tableau de bord. VIVEMENT conseillé si tu l'exposes au réseau
# (JARVIS_ECRAN_HOTE=0.0.0.0) : sinon tes rappels/listes/état maison sont lisibles par
# tout le monde sur le Wi-Fi. Ouvre alors la page avec ...:8765/?jeton=TON_JETON.
DASHBOARD_TOKEN = _env("JARVIS_ECRAN_JETON", "").strip()
# Sentinelle : surveille les signes d'intrusion (nouveaux programmes en écoute, nouveaux
# appareils sur le réseau, pare-feu coupé, menaces Defender...). "0" pour la couper.
SENTINEL = _env("JARVIS_SENTINELLE", "1") == "1"
SENTINEL_FILE = DATA_DIR / "sentinelle.json"

# --- Maison connectée (Home Assistant, local) ---
HA_URL = _env("HOMEASSISTANT_URL", "").strip()      # ex. http://homeassistant.local:8123
HA_TOKEN = _env("HOMEASSISTANT_TOKEN", "").strip()  # jeton d'accès longue durée
# Aspirateur robot (Valetudo via HA) : associe un nom de pièce à son « segment » Valetudo.
# Ex. JARVIS_ASPIRATEUR_PIECES={"salon":"16","cuisine":"17"}
VACUUM_SEGMENTS: dict = _json_env("JARVIS_ASPIRATEUR_PIECES")
# Point de situation : capteurs à surveiller pour donner à Jarvis la « conscience » du moment
# (détections caméra, état du drone, batteries…). Lecture seule. entity_id séparés par des virgules.
TELEMETRIE = tuple(x.strip() for x in _env("JARVIS_TELEMETRIE", "").split(",") if x.strip())
# Arroseur anti-nuisibles (dissuasion par zone) : { "parterre": "switch.arroseur_parterre" }.
ARROSEUR_ZONES: dict = _json_env("JARVIS_ARROSEUR")
# Détection d'objets personnalisée (Ultralytics YOLO) : chemin d'un modèle .pt entraîné par toi.
# Vide = désactivé. « Y a-t-il un colis à l'entrée ? »
YOLO_MODEL = _env("JARVIS_YOLO_MODELE", "").strip()
YOLO_SEUIL = float(_env("JARVIS_YOLO_SEUIL", "0.4"))
# Robot mobile (ROS 2 / Nav2) : destinations autorisées, séparées par des virgules.
# Jarvis envoie l'ordre par MQTT ; un noeud ROS sur le robot fait la navigation.
ROBOT_LIEUX = tuple(x.strip() for x in _env("JARVIS_ROBOT_LIEUX", "").split(",") if x.strip())

# Mode mains libres : secondes d'écoute après une réponse, sans redire « Jarvis ».
AWAKE_SECONDS = float(_env("JARVIS_ECOUTE_SECONDES", "30"))

# Nombre maximum d'allers-retours avec les outils pour une seule question.
MAX_TOOL_ROUNDS = 6
