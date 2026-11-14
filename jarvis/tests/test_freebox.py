"""Tests de l'intégration Freebox (qui est sur le Wi-Fi, défi/réponse)."""

import hashlib
import hmac
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from freebox import (FreeboxClient, build_freebox_tools, classer,  # noqa: E402
                     mot_de_passe_session, normaliser_hotes)


def test_mot_de_passe_session_est_hmac_sha1():
    attendu = hmac.new(b"jeton", b"defi123", hashlib.sha1).hexdigest()
    assert mot_de_passe_session("jeton", "defi123") == attendu


def test_normaliser_hotes():
    hosts = [{"primary_name": "iPhone de Enes", "l2ident": {"id": "AA:BB:CC:DD:EE:FF"}, "active": True},
             {"primary_name": "", "l2ident": {"id": "11:22:33:44:55:66"}, "active": False}]
    out = normaliser_hotes(hosts)
    assert out[0] == {"nom": "iPhone de Enes", "mac": "aa:bb:cc:dd:ee:ff", "actif": True}
    assert out[1]["actif"] is False and out[1]["nom"] == "11:22:33:44:55:66"


def test_classer_connus_et_inconnus():
    hotes = [{"nom": "iPhone", "mac": "aa:bb:cc:dd:ee:ff", "actif": True},
             {"nom": "Intrus", "mac": "99:88:77:66:55:44", "actif": True},
             {"nom": "VieuxPC", "mac": "00:00:00:00:00:00", "actif": False}]
    c = classer(hotes, connus=("aa:bb:cc:dd:ee:ff",))
    assert [h["nom"] for h in c["inconnus"]] == ["Intrus"]      # actif + non connu
    assert [h["nom"] for h in c["connus"]] == ["iPhone"]        # le hors-ligne n'est pas compté


def test_classer_reconnait_par_nom():
    hotes = [{"nom": "Imprimante", "mac": "de:ad:be:ef:00:01", "actif": True}]
    assert classer(hotes, connus=("imprimante",))["inconnus"] == []


# --- Client (requêtes injectées) ---

def _faux_request(reponses):
    """reponses : dict path -> payload Freebox."""
    appels = []

    def request(method, path, headers=None, body=None):
        appels.append((method, path, headers, body))
        return reponses[path]

    request.appels = appels
    return request


def test_ouvrir_session_defi_reponse():
    rep = {
        "/api/v4/login/": {"success": True, "result": {"challenge": "XYZ"}},
        "/api/v4/login/session/": {"success": True, "result": {"session_token": "SESS"}},
    }
    req = _faux_request(rep)
    client = FreeboxClient("http://fbx", "mon-jeton", request=req)
    assert client.ouvrir_session() == "SESS"
    # le mot de passe envoyé est bien le HMAC du défi
    corps_session = [a for a in req.appels if a[1].endswith("/session/")][0][3]
    assert corps_session["password"] == mot_de_passe_session("mon-jeton", "XYZ")


def test_appareils_ouvre_session_puis_liste():
    rep = {
        "/api/v4/login/": {"success": True, "result": {"challenge": "C"}},
        "/api/v4/login/session/": {"success": True, "result": {"session_token": "S"}},
        "/api/v4/lan/browser/pub/": {"success": True, "result":
            [{"primary_name": "TV", "l2ident": {"id": "AA:AA:AA:AA:AA:AA"}, "active": True}]},
    }
    client = FreeboxClient("http://fbx", "jeton", request=_faux_request(rep))
    appareils = client.appareils()
    assert appareils[0]["nom"] == "TV" and appareils[0]["actif"] is True


def test_erreur_freebox_remonte():
    req = _faux_request({"/api/v4/login/": {"success": False, "msg": "jeton invalide"}})
    import pytest
    with pytest.raises(RuntimeError):
        FreeboxClient("http://fbx", "x", request=req).ouvrir_session()


# --- Outil ---

class FauxClient:
    def __init__(self, appareils):
        self._a = appareils

    def appareils(self):
        return self._a


def test_pas_d_outil_sans_jeton(monkeypatch):
    monkeypatch.setattr(config, "FREEBOX_TOKEN", "")
    assert build_freebox_tools() == []


def test_outil_signale_inconnu(monkeypatch):
    monkeypatch.setattr(config, "FREEBOX_TOKEN", "jeton")
    monkeypatch.setattr(config, "FREEBOX_CONNUS", ("aa:bb:cc:dd:ee:ff",))
    client = FauxClient([
        {"nom": "iPhone", "mac": "aa:bb:cc:dd:ee:ff", "actif": True},
        {"nom": "Intrus", "mac": "99:88:77:66:55:44", "actif": True},
    ])
    out = {t.name: t for t in build_freebox_tools(client=client)}["appareils_wifi"].run()
    assert "INCONNU" in out and "Intrus" in out


def test_outil_wifi_sain(monkeypatch):
    monkeypatch.setattr(config, "FREEBOX_TOKEN", "jeton")
    monkeypatch.setattr(config, "FREEBOX_CONNUS", ("aa:bb:cc:dd:ee:ff",))
    client = FauxClient([{"nom": "iPhone", "mac": "aa:bb:cc:dd:ee:ff", "actif": True}])
    out = {t.name: t for t in build_freebox_tools(client=client)}["appareils_wifi"].run()
    assert "sain" in out


def test_outil_freebox_injoignable(monkeypatch):
    monkeypatch.setattr(config, "FREEBOX_TOKEN", "jeton")

    class Ko:
        def appareils(self):
            raise OSError("timeout")
    out = {t.name: t for t in build_freebox_tools(client=Ko())}["appareils_wifi"].run()
    assert "n'arrive pas à joindre la Freebox" in out
