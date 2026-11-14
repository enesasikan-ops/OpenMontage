"""Tests de la voiture connectée (API constructeur via HA — pas de CAN, pas d'OpenPilot)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from vehicle import Vehicle, build_vehicle_tools  # noqa: E402

TRACKER = "device_tracker.voiture"
LOCK = "lock.voiture"
CAPTEURS = {"carburant": "sensor.voiture_carburant", "autonomie": "sensor.voiture_autonomie"}


class FauxHome:
    def __init__(self, etats):
        self._etats = etats
        self.appels = []

    def states(self):
        return self._etats

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id))


def _home():
    return FauxHome([
        {"entity_id": TRACKER, "state": "not_home",
         "attributes": {"latitude": 48.85, "longitude": 2.35}},
        {"entity_id": LOCK, "state": "locked", "attributes": {}},
        {"entity_id": "sensor.voiture_carburant", "state": "62", "attributes": {}},
        {"entity_id": "sensor.voiture_autonomie", "state": "410 km", "attributes": {}},
    ])


def test_localiser():
    v = Vehicle(_home(), TRACKER, LOCK, CAPTEURS)
    out = v.localiser()
    assert "déplacement" in out and "48.85" in out


def test_localiser_a_la_maison():
    h = FauxHome([{"entity_id": TRACKER, "state": "home", "attributes": {}}])
    assert "maison" in Vehicle(h, TRACKER).localiser()


def test_etat():
    out = Vehicle(_home(), TRACKER, LOCK, CAPTEURS).etat()
    assert "verrouillée" in out and "carburant : 62" in out and "410 km" in out


def test_verrouiller():
    h = _home()
    Vehicle(h, TRACKER, LOCK).verrouiller()
    assert ("lock", "lock", LOCK) in h.appels


def test_deverrouiller():
    h = _home()
    Vehicle(h, TRACKER, LOCK).deverrouiller()
    assert ("lock", "unlock", LOCK) in h.appels


def test_pas_de_serrure():
    assert "Aucune serrure" in Vehicle(_home(), TRACKER, "").verrouiller()


def test_injoignable():
    class Ko:
        def states(self): return []
        def call(self, *a, **k): raise OSError("api down")
    assert "n'arrive pas" in Vehicle(Ko(), TRACKER, LOCK).verrouiller()


# --- Outils ---

def test_pas_d_outils_sans_config(monkeypatch):
    monkeypatch.setattr(config, "VEHICLE", False)
    assert build_vehicle_tools(_home()) == []


def test_outils_et_confirmation(monkeypatch):
    monkeypatch.setattr(config, "VEHICLE", True)
    monkeypatch.setattr(config, "VEHICLE_TRACKER", TRACKER)
    monkeypatch.setattr(config, "VEHICLE_LOCK", LOCK)
    monkeypatch.setattr(config, "VEHICLE_SENSORS", CAPTEURS)
    tools = {t.name: t for t in build_vehicle_tools(_home())}
    assert {"localiser_voiture", "etat_voiture", "verrouiller_voiture", "deverrouiller_voiture"} == set(tools)
    # déverrouiller à distance est une action sensible -> confirmation
    assert tools["deverrouiller_voiture"].confirm is not None
    assert "DÉVERROUILLER" in tools["deverrouiller_voiture"].confirm()
    assert tools["verrouiller_voiture"].confirm is None   # verrouiller = sûr, pas de confirmation
