"""Tests de l'audit de posture réseau (détecte, n'exploite pas)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from vulnscan import (build_vulnscan_tools, evaluer_appareil,  # noqa: E402
                      evaluer_reseau, rapport)


def test_telnet_est_critique():
    c = evaluer_appareil({"nom": "ampoule salon", "ports": [{"port": 23}]})
    assert len(c) == 1 and c[0]["gravite"] == "critique" and "Telnet" in c[0]["probleme"]


def test_firmware_obsolete():
    c = evaluer_appareil({"nom": "ampoule", "firmware_obsolete": True})
    assert c[0]["gravite"] == "haute" and "Firmware" in c[0]["probleme"]


def test_identifiants_par_defaut():
    c = evaluer_appareil({"nom": "cam", "identifiants_par_defaut": True})
    assert c[0]["gravite"] == "critique"


def test_appareil_sain():
    assert evaluer_appareil({"nom": "nas", "ports": [{"port": 22}]}) == []   # SSH seul : rien à signaler


def test_tri_par_gravite():
    reseau = [
        {"nom": "a", "ports": [{"port": 80}]},      # moyenne
        {"nom": "b", "ports": [{"port": 23}]},      # critique
        {"nom": "c", "ports": [{"port": 21}]},      # haute
    ]
    constats = evaluer_reseau(reseau)
    assert [c["gravite"] for c in constats] == ["critique", "haute", "moyenne"]


def test_rapport_rien():
    assert "rien de notable" in rapport([])


def test_rapport_liste_et_propose_isolation():
    out = rapport(evaluer_reseau([{"nom": "ampoule salon", "ports": [{"port": 23}]}]))
    assert "ampoule salon" in out and "critique" in out
    assert "je n'agis pas seul" in out.lower()        # action proposée, pas menée


# --- Outil ---

def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "VULNSCAN", False)
    assert build_vulnscan_tools(scan=lambda r: []) == []


def test_outil_audit(monkeypatch):
    monkeypatch.setattr(config, "VULNSCAN", True)
    monkeypatch.setattr(config, "VULNSCAN_RESEAU", "10.0.0.0/24")
    appareils = [{"nom": "ampoule salon", "ports": [{"port": 23}], "firmware_obsolete": True}]
    tools = {t.name: t for t in build_vulnscan_tools(scan=lambda r: appareils)}
    out = tools["audit_reseau"].run()
    assert "ampoule salon" in out and "Telnet" in out and "Firmware" in out


def test_outil_scan_en_panne(monkeypatch):
    monkeypatch.setattr(config, "VULNSCAN", True)

    def boom(reseau):
        raise RuntimeError("nmap n'est pas installé")
    tools = {t.name: t for t in build_vulnscan_tools(scan=boom)}
    assert "pas pu lancer" in tools["audit_reseau"].run()
