"""Tests de la surveillance d'authentification Wi-Fi (FreeRADIUS / 802.1X)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from radius import analyser_ligne, build_radius_tools, rapport, resume  # noqa: E402

OK = ("Tue Jun 10 03:14:02 2025 : Auth: (8) Login OK: [cam-salon] "
      "(from client ap-salon port 0 cli a4-83-e7-00-11-22)")
REJET = ("Tue Jun 10 03:15:10 2025 : Auth: (9) Login incorrect (eap_tls: TLS Alert): "
         "[unknown] (from client ap-salon port 0 cli 99-88-77-66-55-44)")
BRUIT = "Tue Jun 10 03:16:00 2025 : Info: Ready to process requests"


def test_analyse_login_ok():
    ev = analyser_ligne(OK)
    assert ev == {"resultat": "ok", "identite": "cam-salon", "mac": "a4:83:e7:00:11:22"}


def test_analyse_rejet():
    ev = analyser_ligne(REJET)
    assert ev["resultat"] == "rejet" and ev["mac"] == "99:88:77:66:55:44"


def test_ligne_non_auth_ignoree():
    assert analyser_ligne(BRUIT) is None


def test_resume_compte():
    res = resume([OK, OK, REJET, BRUIT])
    assert res["ok"] == 2 and len(res["rejets"]) == 1
    assert res["rejets"][0]["mac"] == "99:88:77:66:55:44"


def test_rapport_sain():
    assert "aucun rejet" in rapport(resume([OK]))


def test_rapport_signale_rejets():
    out = rapport(resume([OK, REJET]))
    assert "REJET" in out and "99:88:77:66:55:44" in out


# --- Outil ---

def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "RADIUS", False)
    assert build_radius_tools(lire=lambda: []) == []


def test_outil_point_auth(monkeypatch):
    monkeypatch.setattr(config, "RADIUS", True)
    tools = {t.name: t for t in build_radius_tools(lire=lambda: [OK, REJET])}
    out = tools["point_authentification_wifi"].run()
    assert "1 connexion" in out and "REJET" in out


def test_outil_journal_absent(monkeypatch):
    monkeypatch.setattr(config, "RADIUS", True)
    monkeypatch.setattr(config, "RADIUS_LOG", "/inexistant/radius.log")

    def manquant():
        raise FileNotFoundError()
    tools = {t.name: t for t in build_radius_tools(lire=manquant)}
    assert "journal RADIUS" in tools["point_authentification_wifi"].run()
