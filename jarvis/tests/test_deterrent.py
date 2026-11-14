"""Tests de l'arroseur anti-nuisibles (dissuasion par zone, jamais du ciblage)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deterrent import Sprinkler, build_deterrent_tools  # noqa: E402

ZONES = {"parterre": "switch.arroseur_parterre", "potager": "switch.arroseur_potager"}


class FauxHome:
    def __init__(self):
        self.appels = []

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id))


def _sp(home, planifies):
    # planifier immédiat : on exécute la coupure tout de suite pour la vérifier
    return Sprinkler(home, ZONES, planifier=lambda s, f: (planifies.append(s), f())[0])


def test_arrose_la_bonne_zone_puis_coupe():
    home, planifies = FauxHome(), []
    out = _sp(home, planifies).arroser("parterre", 8)
    assert ("switch", "turn_on", "switch.arroseur_parterre") in home.appels
    assert ("switch", "turn_off", "switch.arroseur_parterre") in home.appels   # l'eau est coupée
    assert planifies == [8.0] and "parterre" in out


def test_duree_plafonnee():
    home, planifies = FauxHome(), []
    _sp(home, planifies).arroser("parterre", 999)
    assert planifies == [60.0]        # jamais plus d'une minute


def test_zone_approximative():
    home, planifies = FauxHome(), []
    _sp(home, planifies).arroser("le parterre de roses", 5)
    assert ("switch", "turn_on", "switch.arroseur_parterre") in home.appels


def test_zone_inconnue():
    home, planifies = FauxHome(), []
    out = _sp(home, planifies).arroser("toit", 5)
    assert "toit" in out and "parterre" in out
    assert home.appels == []          # rien déclenché


def test_sans_arroseur_configure():
    out = Sprinkler(FauxHome(), {}).arroser("parterre")
    assert "Aucun arroseur" in out


def test_outil():
    tools = build_deterrent_tools(FauxHome(), ZONES)
    assert len(tools) == 1 and tools[0].name == "arroser"
