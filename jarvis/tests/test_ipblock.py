"""Tests du blocage d'IP défensif (confirmé, avec liste blanche)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipblock import IpBlocker  # noqa: E402


def _blocker(tmp_path, liste_blanche=()):
    appliquees, retirees = [], []
    b = IpBlocker(tmp_path / "ip.json",
                  appliquer=appliquees.append, retirer=retirees.append,
                  liste_blanche=liste_blanche)
    return b, appliquees, retirees


def test_bloque_une_ip_publique(tmp_path):
    b, appliquees, _ = _blocker(tmp_path)
    msg = b.bloquer("93.184.216.34")
    assert appliquees == ["93.184.216.34"]
    assert "93.184.216.34" in b.liste()
    assert "bloquée" in msg


def test_ne_bloque_pas_deux_fois(tmp_path):
    b, appliquees, _ = _blocker(tmp_path)
    b.bloquer("93.184.216.34")
    b.bloquer("93.184.216.34")
    assert appliquees == ["93.184.216.34"]        # appliqué une seule fois


def test_refuse_une_ip_interne(tmp_path):
    # On ne bloque JAMAIS son propre réseau (sinon auto-déni de service).
    b, appliquees, _ = _blocker(tmp_path)
    for interne in ("192.168.1.1", "127.0.0.1", "10.0.0.5", "169.254.1.1"):
        with pytest.raises(ValueError):
            b.bloquer(interne)
    assert appliquees == []


def test_refuse_la_liste_blanche(tmp_path):
    b, appliquees, _ = _blocker(tmp_path, liste_blanche=("8.8.8.8",))
    with pytest.raises(ValueError):
        b.bloquer("8.8.8.8")                     # DNS protégé, jamais bloqué
    assert appliquees == []


def test_refuse_une_ip_invalide(tmp_path):
    b, _, _ = _blocker(tmp_path)
    with pytest.raises(ValueError):
        b.bloquer("pas-une-ip")


def test_debloque_est_reversible(tmp_path):
    b, _, retirees = _blocker(tmp_path)
    b.bloquer("93.184.216.34")
    msg = b.debloquer("93.184.216.34")
    assert retirees == ["93.184.216.34"]
    assert "93.184.216.34" not in b.liste()
    assert "débloquée" in msg


def test_persiste_entre_redemarrages(tmp_path):
    b, _, _ = _blocker(tmp_path)
    b.bloquer("93.184.216.34")
    b2 = IpBlocker(tmp_path / "ip.json", appliquer=lambda ip: None, retirer=lambda ip: None)
    assert "93.184.216.34" in b2.liste()           # relu depuis le disque
