"""Tests de la vigilance thermique (plaque oubliée : chaud + durable + maison endormie)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import thermal  # noqa: E402
from thermal import (ThermalGuard, ThermalWatcher, ThermalZone,  # noqa: E402
                     build_thermal_tools, make_thermal_watcher, message_alerte)

ZONES = [ThermalZone("plaque gauche", "sensor.thermique_cuisine", seuil=70, duree=120)]


@pytest.fixture(autouse=True)
def _reset():
    thermal._GUARD = None
    yield
    thermal._GUARD = None


class FakeHome:
    def __init__(self, etats=None):
        self._etats = etats or []

    def states(self):
        return self._etats


def _guard(clock):
    return ThermalGuard(ZONES, horloge=lambda: clock["t"])


def _etats(temp):
    return {"sensor.thermique_cuisine": temp}


# --- Logique de la garde ---

def test_pas_d_alerte_sous_le_seuil():
    clock = {"t": 0}
    g = _guard(clock)
    assert g.verifier(_etats(40), actif=True) == []


def test_alerte_seulement_si_durable():
    clock = {"t": 0}
    g = _guard(clock)
    assert g.verifier(_etats(200), actif=True) == []     # chaud mais depuis 0 s
    clock["t"] = 60
    assert g.verifier(_etats(200), actif=True) == []     # 60 s : pas encore
    clock["t"] = 130
    alertes = g.verifier(_etats(200), actif=True)        # > 120 s
    assert alertes == [("plaque gauche", 200.0)]


def test_pas_d_alerte_si_vigilance_inactive():
    clock = {"t": 0}
    g = _guard(clock)
    g.verifier(_etats(200), actif=False)
    clock["t"] = 200
    assert g.verifier(_etats(200), actif=False) == []    # chaud et durable, mais pas la nuit


def test_pas_de_repetition_puis_rearme_apres_refroidissement():
    clock = {"t": 0}
    g = _guard(clock)
    g.verifier(_etats(200), actif=True)                  # début de l'épisode chaud (t=0)
    clock["t"] = 130
    assert len(g.verifier(_etats(200), actif=True)) == 1
    clock["t"] = 160
    assert g.verifier(_etats(200), actif=True) == []     # déjà alertée
    clock["t"] = 200
    g.verifier(_etats(30), actif=True)                   # refroidi -> réarme
    clock["t"] = 400
    g.verifier(_etats(200), actif=True)                  # nouvel épisode chaud (t=400)
    clock["t"] = 530
    assert len(g.verifier(_etats(200), actif=True)) == 1  # durable à nouveau : réalerte


def test_capteur_indisponible_ignore():
    clock = {"t": 0}
    g = _guard(clock)
    clock["t"] = 200
    assert g.verifier({"sensor.thermique_cuisine": "unavailable"}, actif=True) == []


def test_message_mentionne_zone_et_temperature():
    msg = message_alerte("plaque gauche", 212.0)
    assert "plaque gauche" in msg and "212" in msg and "oublié" in msg


# --- Veille ---

def test_watcher_alerte_quand_actif():
    clock = {"t": 0}
    g = _guard(clock)
    notifs, preuves = [], []

    class Ev:
        def consigner(self, m):
            preuves.append(m)

    home = FakeHome([{"entity_id": "sensor.thermique_cuisine", "state": "200"}])
    w = ThermalWatcher(home, g, notifs.append, actif=lambda: True, evidence=Ev())
    w.un_tour()
    clock["t"] = 130
    w.un_tour()
    assert any("plaque gauche" in n for n in notifs)
    assert preuves and "200" in preuves[0]


# --- Outil + fabrique ---

def _config(monkeypatch):
    monkeypatch.setattr(config, "THERMAL", True)
    monkeypatch.setattr(config, "THERMAL_ZONES",
                        {"plaque gauche": {"capteur": "sensor.thermique_cuisine", "seuil": 70}})
    monkeypatch.setattr(config, "THERMAL_DUREE", 120.0)
    monkeypatch.setattr(config, "THERMAL_INTERVAL", 30.0)
    monkeypatch.setattr(config, "THERMAL_ARME_ENTITE", "")


def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "THERMAL", False)
    assert build_thermal_tools(FakeHome()) == []


def test_point_thermique(monkeypatch):
    _config(monkeypatch)
    home = FakeHome([{"entity_id": "sensor.thermique_cuisine", "state": "212"}])
    tools = build_thermal_tools(home)
    out = tools[0].run()
    assert tools[0].name == "point_thermique"
    assert "plaque gauche" in out and "212" in out and "chaud" in out


def test_make_watcher_partage_la_garde(monkeypatch):
    _config(monkeypatch)
    home = FakeHome()
    build_thermal_tools(home)
    w = make_thermal_watcher(home, lambda m: None)
    assert isinstance(w, ThermalWatcher) and w.guard is thermal._GUARD
