#!/usr/bin/env bash
# installer_embarque.sh — Installe le mini-Jarvis sur l'ORDINATEUR DE BORD du drone
# (Raspberry Pi sous Raspberry Pi OS / Ubuntu, ou NVIDIA Jetson sous Ubuntu — tous ARM/Linux).
#
# À lancer SUR l'ordinateur de bord, par exemple depuis le mini-PC en SSH :
#     ssh pi@<adresse-du-drone> 'bash -s' < installer_embarque.sh
# ou, une fois le dépôt copié sur la carte :
#     cd jarvis && ./installer_embarque.sh
#
# L'ordinateur de bord est petit : on installe un modèle LÉGER (il voit et réagit vite),
# et le difficile part au Jarvis du sol ou au cloud.

set -euo pipefail
cd "$(dirname "$0")"

# Modèles légers par défaut (adaptés à un Pi 5 / Jetson). Modifiables par variables d'env.
MODELE_LOCAL="${JARVIS_MODELE_LOCAL:-qwen2.5:3b}"
MODELE_VISION="${JARVIS_MODELE_VISION:-moondream}"

echo "== 1/6 Vérification du système =="
if [ "$(uname -s)" != "Linux" ]; then
  echo "Ce script est prévu pour l'ordinateur de bord (Linux : Raspberry Pi OS / Ubuntu)."; exit 1
fi
echo "   Architecture : $(uname -m)"

echo "== 2/6 Paquets système =="
if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv python3-pip ffmpeg git
else
  echo "   apt introuvable : installe à la main python3-venv, pip, ffmpeg, git."
fi

echo "== 3/6 Ollama (cerveau + vision en local, build ARM officiel) =="
if ! command -v ollama >/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
# Démarre le service Ollama s'il ne tourne pas déjà.
if ! curl -sf http://localhost:11434/api/version >/dev/null 2>&1; then
  (ollama serve >/tmp/ollama-embarque.log 2>&1 &) ; sleep 5
fi

echo "== 4/6 Environnement Python =="
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install pymavlink   # pilotage du drone (MAVLink)

echo "== 5/6 Modèles légers ($MODELE_LOCAL + vision $MODELE_VISION) =="
ollama pull "$MODELE_LOCAL"
ollama pull "$MODELE_VISION"

echo "== 6/6 Configuration embarquée (.env) =="
if [ ! -f .env ]; then
  cp .env.example .env
  # Réglages adaptés au vol embarqué.
  {
    echo ""
    echo "# --- Réglages ajoutés par installer_embarque.sh (ordinateur de bord) ---"
    echo "JARVIS_MODELE_LOCAL=$MODELE_LOCAL"
    echo "JARVIS_REFLEXION_LOCALE=0"          # réponses directes, plus rapides
    echo "JARVIS_VISION=local"                # la vision reste à bord (privée, hors ligne)
    echo "JARVIS_MODELE_VISION=$MODELE_VISION"
    echo "JARVIS_DRONE=mavlink"               # pilotage du drone DIY
    echo "JARVIS_DRONE_URL=udp:127.0.0.1:14550"  # Pixhawk relié à l'ordinateur de bord
    echo "JARVIS_SENTINELLE=0"                # pas de sentinelle sur le drone
    echo "JARVIS_BRIEFING="                   # pas de briefing du matin en vol
  } >> .env
  echo "   .env créé avec les réglages embarqués."
else
  echo "   .env existe déjà : je n'y touche pas."
fi

echo
echo "✅ Mini-Jarvis installé sur l'ordinateur de bord."
echo "   TESTE D'ABORD DANS LE SIMULATEUR (ArduPilot SITL) — voir DRONE_DIY.md — avant de voler."
echo "   Lancer :  .venv/bin/python main.py"
