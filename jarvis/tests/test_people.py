"""Tests de la mémoire par personne."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from people import PeopleMemory, build_people_tools  # noqa: E402


def _mem(tmp_path):
    return PeopleMemory(tmp_path / "personnes.json")


def test_retenir_et_rappeler(tmp_path):
    m = _mem(tmp_path)
    m.remember("Carlos", "aime le café sans sucre")
    m.remember("carlos", "déteste le froid")       # même personne (casse ignorée)
    about = m.about("CARLOS")
    assert "café sans sucre" in about and "déteste le froid" in about
    assert "Carlos" in about


def test_doublon(tmp_path):
    m = _mem(tmp_path)
    m.remember("Carlos", "aime le café")
    assert "déjà" in m.remember("Carlos", "aime le café")


def test_personne_inconnue(tmp_path):
    assert "ne sais rien" in _mem(tmp_path).about("Sophie")


def test_oublier_un_fait(tmp_path):
    m = _mem(tmp_path)
    m.remember("Carlos", "aime le café")
    m.remember("Carlos", "déteste le froid")
    m.forget("Carlos", "froid")
    about = m.about("Carlos")
    assert "café" in about and "froid" not in about


def test_oublier_tout(tmp_path):
    m = _mem(tmp_path)
    m.remember("Carlos", "aime le café")
    m.forget("Carlos")
    assert "ne sais rien" in m.about("Carlos")
    assert "carlos" not in m.known()


def test_persiste(tmp_path):
    PeopleMemory(tmp_path / "p.json").remember("Carlos", "aime le café")
    assert "café" in PeopleMemory(tmp_path / "p.json").about("Carlos")   # relu du disque


def test_outils(tmp_path):
    tools = build_people_tools(_mem(tmp_path))
    noms = {t.name for t in tools}
    assert noms == {"retenir_sur_personne", "que_sais_tu_sur", "oublier_sur_personne"}
