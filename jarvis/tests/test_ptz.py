"""Tests du pilotage des caméras motorisées (PTZ)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ptz import PatrolController, PtzController, build_ptz_tools  # noqa: E402


def _book(data=None):
    return NS(data=data if data is not None else {
        "jardin": {"host": "192.168.1.50", "user": "admin", "pass": "x"}})


def _book_presets():
    return NS(data={"jardin": {"host": "192.168.1.50", "user": "a", "pass": "x",
                               "presets": {"portail": "1", "allée": "2"}}})


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


# --- La ronde ---

def test_aller_preset_appelle_le_mover():
    vus = []
    ptz = PtzController(_book_presets(), preset_mover=lambda infos, token: vus.append(token))
    ptz.aller_preset("jardin", "2")
    assert vus == ["2"]


def test_ronde_passe_sur_chaque_position_et_decrit():
    vus = []
    ptz = PtzController(_book_presets(), preset_mover=lambda infos, token: vus.append(token))
    descriptions = {"appel": 0}

    def look(camera):
        descriptions["appel"] += 1
        return f"rien à signaler ({descriptions['appel']})"

    patrol = PatrolController(ptz, look, settle_s=0)
    out = patrol.tour("jardin")
    assert vus == ["1", "2"]                       # passe par les deux positions
    assert "portail" in out and "allée" in out     # décrit chaque zone
    assert "Ronde terminée" in out


def test_ronde_sans_positions():
    ptz = PtzController(_book(), preset_mover=lambda *a: None)   # pas de presets
    out = PatrolController(ptz, lambda c: "x").tour("jardin")
    assert "pas de positions" in out


def test_outil_ronde_seulement_avec_look_et_presets():
    assert not any(t.name == "faire_le_tour" for t in build_ptz_tools(_book()))              # pas de look
    assert not any(t.name == "faire_le_tour" for t in build_ptz_tools(_book(), look=lambda c: "x"))  # pas de presets
    tools = build_ptz_tools(_book_presets(), look=lambda c: "x")
    assert any(t.name == "faire_le_tour" for t in tools)
