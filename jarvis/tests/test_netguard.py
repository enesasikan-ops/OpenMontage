"""Tests du garde-fou anti-SSRF."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import web  # noqa: E402
from netguard import url_externe_sure  # noqa: E402


def _resout_vers(ip):
    return lambda host, port: [(None, None, None, None, (ip, 0))]


# --- IP écrites en clair ---

def test_bloque_les_adresses_internes():
    for mauvais in ("http://192.168.1.1/", "http://127.0.0.1:11434",
                    "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data/",
                    "http://[::1]/"):
        ok, raison = url_externe_sure(mauvais)
        assert not ok, mauvais


def test_autorise_une_ip_publique():
    ok, _ = url_externe_sure("https://1.1.1.1/")
    assert ok


# --- Schémas ---

def test_bloque_les_schemas_dangereux():
    assert not url_externe_sure("file:///etc/passwd")[0]
    assert not url_externe_sure("ftp://exemple.fr")[0]
    assert not url_externe_sure("gopher://x")[0]


# --- Résolution d'un nom ---

def test_nom_qui_resout_vers_une_ip_interne_est_bloque():
    ok, raison = url_externe_sure("https://interne.exemple.fr",
                                  resolveur=_resout_vers("192.168.0.42"))
    assert not ok and "interne" in raison


def test_nom_public_autorise():
    ok, _ = url_externe_sure("https://exemple.fr", resolveur=_resout_vers("93.184.216.34"))
    assert ok


# --- Intégration : read_page refuse une adresse interne ---

def test_read_page_refuse_une_adresse_interne(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    out = web.read_page("http://192.168.1.1/admin")
    assert "refuse" in out.lower()
