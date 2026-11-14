"""Tests du battement de cœur (détecteur d'homme mort)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from heartbeat import HeartbeatEmitter, make_heartbeat  # noqa: E402


def test_battement_publie_retenu():
    envoyes = []
    h = HeartbeatEmitter(publier=lambda t, c, r: envoyes.append((t, c, r)),
                         topic="jarvis/coeur", charge="online")
    assert h.battement() is True
    assert envoyes == [("jarvis/coeur", "online", True)]      # retained : un abonné tardif voit l'état


def test_battement_tolere_une_panne_mqtt():
    def boom(t, c, r):
        raise OSError("mqtt down")
    h = HeartbeatEmitter(publier=boom)
    assert h.battement() is False                             # pas de plantage : le reste de Jarvis vit


def test_make_heartbeat_desactive(monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT", False)
    assert make_heartbeat() is None


def test_make_heartbeat_pret(monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT", True)
    monkeypatch.setattr(config, "HEARTBEAT_TOPIC", "maison/jarvis")
    monkeypatch.setattr(config, "HEARTBEAT_INTERVAL", 15.0)
    h = make_heartbeat()
    assert isinstance(h, HeartbeatEmitter) and h.topic == "maison/jarvis" and h.interval_s == 15.0
