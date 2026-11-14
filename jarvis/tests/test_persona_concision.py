"""Tests du réglage de concision (réponse à « trop bavard », sans DSPy)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import persona  # noqa: E402


def test_normal_n_ajoute_rien(monkeypatch):
    monkeypatch.setattr(config, "CONCISION", "normal")
    assert persona.concision() == ""


def test_militaire(monkeypatch):
    monkeypatch.setattr(config, "CONCISION", "militaire")
    d = persona.concision()
    assert "MILITAIRE" in d and "UNE phrase" in d


def test_bref(monkeypatch):
    monkeypatch.setattr(config, "CONCISION", "bref")
    assert "BREF" in persona.concision()


def test_concision_injectee_dans_le_character(monkeypatch):
    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "CONCISION", "militaire")
    assert "MILITAIRE" in persona.character()
    monkeypatch.setattr(config, "CONCISION", "normal")
    assert "MILITAIRE" not in persona.character()


def test_valeur_inconnue_tombe_sur_normal(monkeypatch):
    monkeypatch.setattr(config, "CONCISION", "nimportequoi")
    assert persona.concision() == ""
