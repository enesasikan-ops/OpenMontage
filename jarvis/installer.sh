#!/usr/bin/env bash
# Installation de Jarvis sur macOS (Mac mini Apple Silicon).
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/5 Homebrew, Python, Ollama et ffmpeg =="
if ! command -v brew >/dev/null; then
  echo "Installe d'abord Homebrew : https://brew.sh puis relance ce script."; exit 1
fi
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list --cask ollama >/dev/null 2>&1 || brew install --cask ollama
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg
open -a Ollama || true

echo "== 2/5 Environnement Python =="
[ -d .venv ] || "$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

echo "== 3/5 Voix française (Piper) =="
mkdir -p voix
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR"
for v in tom siwis; do  # tom = voix d'homme (défaut), siwis = voix de femme
  for f in "fr_FR-$v-medium.onnx" "fr_FR-$v-medium.onnx.json"; do
    [ -f "voix/$f" ] || curl -fL -o "voix/$f" "$BASE/$v/medium/$f"
  done
done

echo "== 4/5 Fichier de configuration =="
[ -f .env ] || cp .env.example .env

echo "== 5/5 Modèle local =="
MODEL="$(grep -E '^JARVIS_MODELE_LOCAL=' .env | cut -d= -f2)"
MODEL="${MODEL:-mistral-small3.2}"
sleep 3
ollama pull "$MODEL"

echo
echo "== Préchargement de Whisper (pour pouvoir passer hors ligne ensuite) =="
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

echo
if command -v claude >/dev/null; then
  echo "✅ Claude Code est installé : le renfort passera par ton abonnement."
  echo "   Si ce n'est pas déjà fait, lance « claude » une fois et connecte-toi."
else
  echo "ℹ️  Pour le renfort Claude via ton abonnement :"
  echo "   brew install --cask claude-code   puis lance « claude » une fois pour te connecter."
fi
echo
echo "✅ Installé. Pour lancer Jarvis :"
echo "   .venv/bin/python main.py          # au clavier"
echo "   .venv/bin/python main.py --voix   # à la voix"
echo "   .venv/bin/python telegram_bot.py  # sur Telegram (voir le README)"
