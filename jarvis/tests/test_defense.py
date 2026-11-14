"""Tests de la défense active : journal de preuves et restauration du cœur."""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from defense import CoreBackup, EvidenceLog  # noqa: E402

FICHIERS = ("a.py", "b.py")


# --- Journal de preuves ---

def test_journal_consigne_et_horodate(tmp_path):
    horloge = lambda: datetime(2026, 11, 13, 9, 30, 0)
    ev = EvidenceLog(tmp_path / "preuves.json", horloge=horloge)
    ev.consigner("fichier du cœur MODIFIÉ : brain.py")
    r = ev.recent()
    assert r[-1]["quoi"] == "fichier du cœur MODIFIÉ : brain.py"
    assert r[-1]["quand"].startswith("2026-11-13T09:30")


def test_journal_persiste(tmp_path):
    p = tmp_path / "preuves.json"
    EvidenceLog(p).consigner("alerte 1")
    assert EvidenceLog(p).recent()[-1]["quoi"] == "alerte 1"   # relu depuis le disque


# --- Sauvegarde / restauration du cœur ---

def _backup(tmp_path):
    (tmp_path / "a.py").write_text("bon code a\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("bon code b\n", encoding="utf-8")
    b = CoreBackup(tmp_path / "sauvegarde", racine=tmp_path, fichiers=FICHIERS)
    b.sauvegarder()
    return b


def test_restaure_un_fichier_trafique(tmp_path):
    b = _backup(tmp_path)
    (tmp_path / "a.py").write_text("code PIRATÉ\n", encoding="utf-8")   # altération
    msg = b.restaurer("a.py")
    assert (tmp_path / "a.py").read_text() == "bon code a\n"           # remis d'aplomb
    assert "restauré" in msg


def test_restaure_refuse_un_fichier_hors_coeur(tmp_path):
    b = _backup(tmp_path)
    with pytest.raises(ValueError):
        b.restaurer("c.py")


def test_restaure_sans_sauvegarde_leve(tmp_path):
    (tmp_path / "a.py").write_text("x\n", encoding="utf-8")
    b = CoreBackup(tmp_path / "vide", racine=tmp_path, fichiers=FICHIERS)  # jamais sauvegardé
    assert not b.peut_restaurer("a.py")
    with pytest.raises(ValueError):
        b.restaurer("a.py")
