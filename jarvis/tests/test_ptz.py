"""Tests du pilotage des caméras motorisées (PTZ)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptz import PtzController, build_ptz_tools  # noqa: E402


def _book(data=None):
    return NS(data=data if data is not None else {
        "jardin": {"host": "192.168.1.50", "user": "admin", "pass": "x"}})


def test_tourner_envoie_la_bonne_direction():
    vus = []
    ptz = PtzController(_book(), mover=lambda infos, pan, tilt, duree: vus.append((pan, tilt, duree)))
    out = ptz.tourner("jardin", "gauche")
    assert vus == [(-0.5, 0.0, 1.0)]        # gauche = pan négatif
    assert "gauche" in out

    vus.clear()
    ptz.tourner("jardin", "haut", duree=2)
    assert vus == [(0.0, 0.5, 2.0)]         # haut = tilt positif


def test_duree_plafonnee():
    vus = []
    ptz = PtzController(_book(), mover=lambda i, p, t, d: vus.append(d))
    ptz.tourner("jardin", "droite", duree=99)
    assert vus == [5.0]                      # jamais plus de 5 s d'un coup


def test_camera_inconnue():
    ptz = PtzController(_book(), mover=lambda *a: None)
    out = ptz.tourner("salon", "gauche")
    assert "ne connais pas" in out


def test_direction_inconnue():
    ptz = PtzController(_book(), mover=lambda *a: None)
    assert "Direction inconnue" in ptz.tourner("jardin", "diagonale")


def test_erreur_materielle_ne_plante_pas():
    def boom(*a):
        raise RuntimeError("caméra injoignable")
    ptz = PtzController(_book(), mover=boom)
    assert "n'arrive pas" in ptz.tourner("jardin", "gauche")


# --- L'outil n'apparaît que si des caméras PTZ sont configurées ---

def test_outil_absent_sans_camera_ptz():
    assert build_ptz_tools(NS(data={})) == []


def test_outil_present_avec_camera_ptz():
    tools = build_ptz_tools(_book())
    assert len(tools) == 1 and tools[0].name == "tourner_camera"
