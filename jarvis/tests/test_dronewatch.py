"""Tests de la veille aérienne (détection de drones Remote ID : alerte + preuve, pas de traque)."""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import dronewatch  # noqa: E402
from dronewatch import DroneLog, DroneWatcher, analyser, build_drone_tools, message  # noqa: E402


def _ev(**kw):
    base = {"uas_id": "DRN-1", "lat": 48.85, "lon": 2.35, "altitude": 60,
            "operator_lat": 48.84, "operator_lon": 2.36}
    base.update(kw)
    return json.dumps(base).encode()


def test_analyse_detection():
    d = analyser(_ev())
    assert d["id"] == "DRN-1" and d["altitude"] == 60 and d["operateur_lat"] == 48.84


def test_analyse_sans_position_ignoree():
    assert analyser(json.dumps({"uas_id": "x"}).encode()) is None


def test_analyse_json_invalide():
    assert analyser(b"pas json") is None


def test_message_oriente_conscience_pas_traque():
    m = message({"altitude": 60})
    assert "Drone détecté" in m and "police" in m
    assert "confront" not in m.lower()        # on invite à noter, pas à agir


# --- Watcher : alerte + preuve + anti-répétition ---

def _watcher(clock, evidence=None):
    return DroneWatcher(lambda m: notifs.append(m), evidence=evidence,
                        horloge=lambda: clock["t"], cooldown_s=120)


notifs = []


def setup_function():
    notifs.clear()
    dronewatch._LOG = None


def test_detection_alerte_et_consigne():
    preuves = []

    class Ev:
        def consigner(self, m):
            preuves.append(m)

    clock = {"t": 0}
    _watcher(clock, Ev()).traiter(_ev())
    assert any("Drone détecté" in n for n in notifs)
    assert preuves and "DRN-1" in preuves[0] and "opérateur" in preuves[0]   # preuve inclut l'opérateur


def test_cooldown_anti_repetition():
    clock = {"t": 0}
    w = _watcher(clock)
    w.traiter(_ev()); w.traiter(_ev())          # même drone tout de suite
    assert len(notifs) == 1
    clock["t"] = 200
    w.traiter(_ev())
    assert len(notifs) == 2                      # après le cooldown : réalerte


def test_journal_et_outil(monkeypatch):
    monkeypatch.setattr(config, "DRONEWATCH", True)
    log = DroneLog(horloge=lambda: datetime(2025, 1, 1, 22, 30))
    log.noter(analyser(_ev()))
    assert "DRN-1" in log.resume() and "enregistré" in log.resume().lower()
    tools = {t.name: t for t in build_drone_tools()}
    assert "point_aerien" in tools


def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "DRONEWATCH", False)
    assert build_drone_tools() == []
