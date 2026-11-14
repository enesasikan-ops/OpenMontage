"""Tests du second modèle local consultable (outil de parole, pas d'action)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from secondmodel import SecondModel, build_second_model_tools  # noqa: E402


def test_demander_route_vers_le_modele():
    recu = {}

    def chat(modele, messages):
        recu["modele"] = modele
        recu["msg"] = messages[0]["content"]
        return "  voici ma réponse  "

    out = SecondModel("dolphin-llama3", chat=chat).demander("explique les RAID")
    assert recu["modele"] == "dolphin-llama3" and recu["msg"] == "explique les RAID"
    assert out == "voici ma réponse"            # nettoyé


def test_question_vide():
    assert "Quelle est la question" in SecondModel("x", chat=lambda m, msg: "").demander("  ")


def test_modele_absent_message_clair():
    def boom(modele, messages):
        raise RuntimeError("model not found")
    out = SecondModel("dolphin-llama3", chat=boom).demander("salut")
    assert "n'a pas répondu" in out and "ollama pull dolphin-llama3" in out


def test_reponse_vide():
    assert "rien renvoyé" in SecondModel("x", chat=lambda m, msg: "").demander("q")


# --- Outil ---

def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "SECOND_MODEL", "")
    assert build_second_model_tools() == []


def test_outil_present_et_fonctionne(monkeypatch):
    monkeypatch.setattr(config, "SECOND_MODEL", "dolphin-llama3")
    tools = {t.name: t for t in build_second_model_tools(chat=lambda m, msg: f"[{m}] ok")}
    assert tools["demander_au_modele_local"].run(question="test") == "[dolphin-llama3] ok"
    assert "dolphin-llama3" in tools["demander_au_modele_local"].description
