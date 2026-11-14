"""Tests du journal des personnes vues (« qui as-tu vu ? »)."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sightings  # noqa: E402
from sightings import SightingLog, build_sighting_tools  # noqa: E402


def _log(base):
    horloge = {"t": base}
    return SightingLog(horloge=lambda: horloge["t"]), horloge


BASE = datetime(2025, 1, 1, 20, 0, 0)


def test_vide():
    log, _ = _log(BASE)
    assert "personne" in log.resume()


def test_note_connu_et_inconnu():
    log, h = _log(BASE)
    log.noter("carlos", "porte", True)
    h["t"] = BASE + timedelta(minutes=5)
    log.noter(None, "jardin", False)
    h["t"] = BASE + timedelta(minutes=6)
    out = log.resume()
    assert "Carlos" in out and "un inconnu" in out and "porte" in out and "jardin" in out


def test_temps_relatif():
    log, h = _log(BASE)
    log.noter("ana", "entree", True)
    h["t"] = BASE + timedelta(minutes=12)
    assert "il y a 12 min" in log.resume()


def test_ordre_plus_recent_d_abord():
    log, h = _log(BASE)
    log.noter("ana", "a", True)
    h["t"] = BASE + timedelta(minutes=1)
    log.noter("bob", "b", True)
    h["t"] = BASE + timedelta(minutes=2)
    out = log.resume()
    assert out.index("Bob") < out.index("Ana")       # le plus récent d'abord


def test_anneau_borne():
    log, _ = _log(BASE)
    petit = SightingLog(taille=3, horloge=lambda: BASE)
    for i in range(5):
        petit.noter(f"p{i}", "cam", True)
    assert len(petit.recents(10)) == 3               # ne garde que les 3 derniers


# --- Outil + singleton ---

def test_outil_utilise_le_journal(monkeypatch):
    monkeypatch.setattr(sightings, "_JOURNAL", None)
    sightings.journal().noter("zoe", "porte", True)
    tool = build_sighting_tools()[0]
    assert tool.name == "qui_as_tu_vu" and "Zoe" in tool.run()
