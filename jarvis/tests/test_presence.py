"""Tests de la carte de présence (occupation anonyme par pièce)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from presence import (build_presence_tools, maison_vide, occupees,  # noqa: E402
                      pieces_config)

PIECES = {"salon": "binary_sensor.salon", "cuisine": "binary_sensor.cuisine"}


class FakeHome:
    def __init__(self, etats):
        self._etats = etats

    def states(self):
        return [{"entity_id": k, "state": v} for k, v in self._etats.items()]


def test_occupees():
    etats = {"binary_sensor.salon": "on", "binary_sensor.cuisine": "off"}
    assert occupees(etats, PIECES) == {"salon"}


def test_occupees_tolere_variantes():
    assert occupees({"binary_sensor.salon": "occupied"}, PIECES) == {"salon"}


def test_maison_vide():
    assert maison_vide({"binary_sensor.salon": "off", "binary_sensor.cuisine": "off"}, PIECES) is True
    assert maison_vide({"binary_sensor.salon": "on"}, PIECES) is False
    assert maison_vide({}, {}) is False        # pas de pièces configurées -> indéterminé


def test_pieces_config(monkeypatch):
    monkeypatch.setattr(config, "PRESENCE_PIECES", {"salon": "binary_sensor.x", "vide": ""})
    assert pieces_config() == {"salon": "binary_sensor.x"}


def test_pas_d_outils_sans_config(monkeypatch):
    monkeypatch.setattr(config, "PRESENCE_PIECES", {})
    assert build_presence_tools(FakeHome({})) == []


def test_outils(monkeypatch):
    monkeypatch.setattr(config, "PRESENCE_PIECES", PIECES)
    home = FakeHome({"binary_sensor.salon": "on", "binary_sensor.cuisine": "off"})
    tools = {t.name: t for t in build_presence_tools(home)}
    assert set(tools) == {"pieces_occupees", "piece_occupee", "maison_vide"}
    assert "salon" in tools["pieces_occupees"].run()
    assert "occupée" in tools["piece_occupee"].run(piece="salon")
    assert "vide" in tools["piece_occupee"].run(piece="cuisine")
    assert "du monde" in tools["maison_vide"].run()


def test_outil_piece_inconnue(monkeypatch):
    monkeypatch.setattr(config, "PRESENCE_PIECES", PIECES)
    tools = {t.name: t for t in build_presence_tools(FakeHome({}))}
    out = tools["piece_occupee"].run(piece="grenier")
    assert "grenier" in out and "salon" in out


def test_maison_vide_outil(monkeypatch):
    monkeypatch.setattr(config, "PRESENCE_PIECES", PIECES)
    home = FakeHome({"binary_sensor.salon": "off", "binary_sensor.cuisine": "off"})
    tools = {t.name: t for t in build_presence_tools(home)}
    assert "vide" in tools["maison_vide"].run()
