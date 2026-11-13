"""Tests de la vision (locale via Ollama, ou Gemini), sans modèle ni réseau réels."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from vision import VisionRouter  # noqa: E402

IMG = b"\xff\xd8\xff fake jpeg"


class FakeOllama:
    def __init__(self, text="Je vois un salon lumineux."):
        self.text = text
        self.calls = []

    def chat(self, model, messages):
        self.calls.append((model, messages))
        return {"message": {"content": self.text}}


def gemini(available=True, text="Gemini voit un jardin."):
    return NS(available=available, describe_image=lambda img, q="": text)


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(config, "VISION", "auto")
    monkeypatch.setattr(config, "VISION_MODEL", "")
    monkeypatch.setattr(config, "OLLAMA_HOST", "http://localhost:11434")


def test_auto_prefers_local_when_model_set(monkeypatch):
    monkeypatch.setattr(config, "VISION_MODEL", "qwen2.5-vl")
    ol = FakeOllama()
    r = VisionRouter(ollama_client=ol, gemini=gemini())
    assert r.mode == "local"
    assert r.describe(IMG) == "Je vois un salon lumineux."
    model, messages = ol.calls[0]
    assert model == "qwen2.5-vl"
    assert messages[0]["images"] == [IMG]            # l'image passe bien au modèle local


def test_auto_falls_back_to_gemini_without_local_model():
    r = VisionRouter(gemini=gemini())
    assert r.mode == "gemini"
    assert r.describe(IMG) == "Gemini voit un jardin."


def test_auto_none_when_nothing_available():
    r = VisionRouter(gemini=gemini(available=False))
    assert not r.available
    assert "pas configurée" in r.describe(IMG)


def test_forced_local_needs_model(monkeypatch):
    monkeypatch.setattr(config, "VISION", "local")
    assert VisionRouter(gemini=gemini()).mode == "none"   # pas de modèle local réglé
    monkeypatch.setattr(config, "VISION_MODEL", "moondream")
    assert VisionRouter(ollama_client=FakeOllama(), gemini=gemini()).mode == "local"


def test_forced_gemini(monkeypatch):
    monkeypatch.setattr(config, "VISION", "gemini")
    monkeypatch.setattr(config, "VISION_MODEL", "qwen2.5-vl")  # ignoré en mode gemini
    r = VisionRouter(ollama_client=FakeOllama(), gemini=gemini())
    assert r.mode == "gemini" and r.describe(IMG) == "Gemini voit un jardin."


def test_local_model_error_is_friendly(monkeypatch):
    monkeypatch.setattr(config, "VISION_MODEL", "qwen2.5-vl")

    class Broken(FakeOllama):
        def chat(self, model, messages):
            raise RuntimeError("model not found")

    out = VisionRouter(ollama_client=Broken(), gemini=None).describe(IMG)
    assert "qwen2.5-vl" in out and ("installé" in out or "pull" in out)


def test_empty_image():
    assert "pas d'image" in VisionRouter(gemini=gemini()).describe(b"")


def test_drone_uses_vision_router():
    """Le drone appelle bien la vision via le routeur (local ou Gemini)."""
    from drone import DronePilot, SimDrone

    router = VisionRouter(gemini=gemini(text="Je vois le jardin, Monsieur."))
    pilot = DronePilot(SimDrone(), describe=router.describe)
    pilot.takeoff()
    assert pilot.look() == "Je vois le jardin, Monsieur."
