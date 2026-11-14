"""Tests du kill-switch visuel tondeuse (arrêt autonome, reprise prudente)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mower  # noqa: E402
from mower import (MowerGuard, MowerWatcher, analyser_frigate,  # noqa: E402
                   build_mower_tools, make_mower_watcher)

ZONES = ("pelouse",)
LABELS = ("person", "dog", "cat")


@pytest.fixture(autouse=True)
def _reset():
    mower._GUARD = None
    yield
    mower._GUARD = None


class FakeStore:
    def __init__(self):
        self.data = {}

    def save(self):
        pass


def _ev(label="person", zones=("pelouse",), camera="jardin", type_="new"):
    return json.dumps({"type": type_,
                       "after": {"label": label, "camera": camera, "current_zones": list(zones)}}).encode()


def _guard(clock, reprise_auto=True, reprise_delai=60):
    publies = []
    notifs = []
    g = MowerGuard(lambda t, c: publies.append((t, c)), notifs.append, FakeStore(),
                   settings={"topic": "mower/command", "stop": "stop", "start": "start",
                             "reprise_auto": reprise_auto, "reprise_delai": reprise_delai},
                   horloge=lambda: clock["t"])
    return g, publies, notifs


# --- Analyse Frigate ---

def test_personne_dans_la_zone():
    assert analyser_frigate(_ev(), ZONES, "jardin", LABELS)["label"] == "person"


def test_chien_detecte():
    assert analyser_frigate(_ev(label="dog"), ZONES, "", LABELS) is not None


def test_objet_non_surveille_ignore():
    assert analyser_frigate(_ev(label="car"), ZONES, "", LABELS) is None


def test_hors_zone_ignore():
    assert analyser_frigate(_ev(zones=("allee",)), ZONES, "", LABELS) is None


# --- Arrêt (autonome, immédiat) ---

def test_detection_coupe_les_lames_si_arme():
    clock = {"t": 0}
    g, publies, notifs = _guard(clock)
    g.armer()
    g.sur_detection({"label": "person"})
    assert ("mower/command", "stop") in publies
    assert any("immobilisée" in n for n in notifs)


def test_rien_si_desarme():
    clock = {"t": 0}
    g, publies, _ = _guard(clock)
    g.sur_detection({"label": "person"})
    assert publies == []


def test_pas_de_double_arret():
    clock = {"t": 0}
    g, publies, _ = _guard(clock)
    g.armer()
    g.sur_detection({}); g.sur_detection({})
    assert [p for p in publies if p[1] == "stop"] == [("mower/command", "stop")]


# --- Reprise (prudente) ---

def test_pas_de_reprise_tant_que_danger_recent():
    clock = {"t": 0}
    g, publies, _ = _guard(clock, reprise_delai=60)
    g.armer()
    g.sur_detection({})
    clock["t"] = 30
    assert g.tic() is None                      # 30 s < 60 s : on ne relance pas
    assert ("mower/command", "start") not in publies


def test_reprise_apres_perimetre_degage_longtemps():
    clock = {"t": 0}
    g, publies, notifs = _guard(clock, reprise_delai=60)
    g.armer()
    g.sur_detection({})
    clock["t"] = 61
    assert g.tic() == "reprise"
    assert ("mower/command", "start") in publies
    assert any("reprend" in n for n in notifs)


def test_reprise_manuelle_ne_redemarre_pas_seule():
    clock = {"t": 0}
    g, publies, _ = _guard(clock, reprise_auto=False)
    g.armer()
    g.sur_detection({})
    clock["t"] = 9999
    assert g.tic() is None                      # mode manuel : jamais de reprise auto
    assert ("mower/command", "start") not in publies


def test_commandes_manuelles():
    clock = {"t": 0}
    g, publies, _ = _guard(clock)
    g.arreter_maintenant()
    g.reprendre_maintenant()
    assert ("mower/command", "stop") in publies and ("mower/command", "start") in publies


# --- Watcher + outils ---

def test_watcher_traite_detection():
    clock = {"t": 0}
    g, publies, _ = _guard(clock)
    g.armer()
    MowerWatcher(g, ZONES, "jardin", LABELS).traiter(_ev())
    assert ("mower/command", "stop") in publies


def test_pas_d_outils_sans_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "MOWER", False)
    assert build_mower_tools(lambda m: None) == []


class FakeHome:
    def __init__(self):
        self.appels = []

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id))


def test_backend_home_assistant(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "MOWER", True)
    monkeypatch.setattr(config, "MOWER_ZONES", ZONES)
    monkeypatch.setattr(config, "MOWER_FILE", tmp_path / "t.json")
    monkeypatch.setattr(config, "MOWER_BACKEND", "ha")
    monkeypatch.setattr(config, "MOWER_ENTITE", "lawn_mower.jardin")
    home = FakeHome()
    g = mower.guard(lambda m: None, home)
    g.armer()
    g.sur_detection({"label": "person"})
    assert ("lawn_mower", "pause", "lawn_mower.jardin") in home.appels   # pause = arrêt sur place
    g.reprendre_maintenant()
    assert ("lawn_mower", "start_mowing", "lawn_mower.jardin") in home.appels


def test_outils_et_make_partagent_la_garde(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "MOWER", True)
    monkeypatch.setattr(config, "MOWER_ZONES", ZONES)
    monkeypatch.setattr(config, "MOWER_CAMERA", "")
    monkeypatch.setattr(config, "MOWER_LABELS", LABELS)
    monkeypatch.setattr(config, "MOWER_FILE", tmp_path / "t.json")
    noms = {t.name for t in build_mower_tools(lambda m: None)}
    assert {"armer_tondeuse", "arreter_tondeuse", "reprendre_tondeuse"} <= noms
    assert make_mower_watcher(lambda m: None).guard is mower._GUARD
