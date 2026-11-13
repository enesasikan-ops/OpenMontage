#!/usr/bin/env bash
# Installation de Jarvis sur macOS (Mac mini Apple Silicon).
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/5 Homebrew, Python et Ollama =="
if ! command -v brew >/dev/null; then
  echo "Installe d'abord Homebrew : https://brew.sh puis relance ce script."; exit 1
fi
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
brew list --cask ollama >/dev/null 2>&1 || brew install --cask ollama
open -a Ollama || true

echo "== 2/5 Environnement Python =="
[ -d .venv ] || "$(brew --prefix python@3.12)/bin/python3.12" -m venv .venv
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

echo "== 3/5 Voix française (Piper) =="
mkdir -p voix
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium"
for f in fr_FR-siwis-medium.onnx fr_FR-siwis-medium.onnx.json; do
  [ -f "voix/$f" ] || curl -fL -o "voix/$f" "$BASE/$f"
done

echo "== 4/5 Fichier de configuration =="
[ -f .env ] || cp .env.example .env

echo "== 5/5 Modèle local =="
MODEL="$(grep -E '^JARVIS_MODELE_LOCAL=' .env | cut -d= -f2)"
MODEL="${MODEL:-mistral-small3.2}"
sleep 3
ollama pull "$MODEL"

echo
echo "✅ Installé. Ajoute ta clé ANTHROPIC_API_KEY dans .env (facultatif), puis :"
echo "   .venv/bin/python main.py          # au clavier"
echo "   .venv/bin/python main.py --voix   # à la voix"
