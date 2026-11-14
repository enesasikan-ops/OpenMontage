"""Tests du pont vers le robot mobile (ROS 2)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from robot import RobotCourier, build_robot_tools  # noqa: E402

LIEUX = ("garage", "salon", "cuisine")


def _courier():
    envoyes = []
    return RobotCourier(LIEUX, publier=lambda topic, payload: envoyes.append(json.loads(payload))), envoyes


def test_envoi_a_un_lieu_connu():
    c, envoyes = _courier()
    out = c.aller("garage")
    assert envoyes == [{"action": "aller", "destination": "garage"}]
    assert "garage" in out


def test_lieu_inconnu_rien_envoye():
    c, envoyes = _courier()
    out = c.aller("grenier")
    assert envoyes == []
    assert "grenier" in out and "garage" in out   # propose les lieux connus


def test_casse_ignoree():
    c, envoyes = _courier()
    c.aller("GARAGE")
    assert envoyes[0]["destination"] == "garage"


def test_retour_et_arret():
    c, envoyes = _courier()
    c.revenir()
    c.arreter()
    actions = [e["action"] for e in envoyes]
    assert actions == ["retour", "stop"]


def test_robot_injoignable():
    def boom(topic, payload):
        raise OSError("mqtt down")
    c = RobotCourier(LIEUX, publier=boom)
    assert "n'arrive pas" in c.aller("garage")


# --- Les outils n'existent que si des lieux sont configurés ---

def test_pas_d_outils_sans_lieux(monkeypatch):
    monkeypatch.setattr(config, "ROBOT_LIEUX", ())
    assert build_robot_tools() == []


def test_outils_avec_lieux():
    noms = {t.name for t in build_robot_tools(LIEUX)}
    assert noms == {"envoyer_robot", "rappeler_robot", "arreter_robot"}
