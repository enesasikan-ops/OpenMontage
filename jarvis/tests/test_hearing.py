"""Tests de l'ouïe analytique (classification des sons)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hearing import SoundWatcher, _reconnaitre  # noqa: E402


def test_reconnaissance_des_sons():
    assert _reconnaitre("Glass") == "bris de glace"
    assert _reconnaitre("Shatter") == "bris de glace"
    assert _reconnaitre("Smoke detector, smoke alarm") == "alarme incendie"
    assert _reconnaitre("Gunshot, gunfire") == "coup de feu"
    assert _reconnaitre("Speech") is None            # parole : pas un son surveillé
    assert _reconnaitre("Music") is None


def test_alerte_sur_son_surveille():
    vus = []
    w = SoundWatcher(lambda fr, label, score: vus.append((fr, round(score, 2))))
    out = w.traiter([("Speech", 0.6), ("Glass", 0.82), ("Music", 0.3)])
    assert out[0] == "bris de glace"
    assert vus == [("bris de glace", 0.82)]


def test_sous_le_seuil_rien():
    vus = []
    w = SoundWatcher(lambda *a: vus.append(a), seuil=0.5)
    assert w.traiter([("Glass", 0.3)]) is None       # trop faible
    assert vus == []


def test_son_non_surveille_ignore():
    vus = []
    w = SoundWatcher(lambda *a: vus.append(a))
    assert w.traiter([("Dishes", 0.9), ("Typing", 0.8)]) is None
    assert vus == []


def test_pas_deux_alertes_rapprochees():
    vus = []
    w = SoundWatcher(lambda *a: vus.append(a))
    w.traiter([("Glass", 0.9)])
    w.traiter([("Glass", 0.9)])      # juste après : ignoré (anti-répétition)
    assert len(vus) == 1
