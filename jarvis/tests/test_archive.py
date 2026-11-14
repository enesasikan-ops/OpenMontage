"""Tests de la mémoire d'archive (cherchée à la demande, pas chargée dans le prompt)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from archive import Archive, build_archive_tools  # noqa: E402


def test_archiver_et_persister(tmp_path):
    a = Archive(tmp_path / "a.json")
    a.archiver("l'utilisateur préfère la température du salon à 20 degrés le soir", quand="2024-01-10")
    assert len(Archive(tmp_path / "a.json").entrees) == 1


def test_recherche_par_mots_cles(tmp_path):
    a = Archive(tmp_path / "a.json")
    a.archiver("préférence chauffage salon à 20 degrés", quand="2024-01-01")
    a.archiver("code du portail changé en 4731", quand="2024-02-01")
    a.archiver("rendez-vous dentiste à Lyon", quand="2024-03-01")
    res = a.chercher("quel chauffage dans le salon")
    assert res and "chauffage salon" in res[0]["texte"]
    assert all("dentiste" not in e["texte"] for e in res)


def test_tri_par_score_puis_recence(tmp_path):
    a = Archive(tmp_path / "a.json")
    a.archiver("voyage voiture", quand="2024-01-01")              # 1 mot commun
    a.archiver("voyage voiture Lyon weekend", quand="2024-02-01")  # 2 mots communs
    res = a.chercher("voyage voiture")
    assert res[0]["date"] == "2024-02-01"                         # meilleur score d'abord


def test_recherche_vide(tmp_path):
    a = Archive(tmp_path / "a.json")
    a.archiver("quelque chose", quand="2024-01-01")
    assert a.chercher("xyzinconnu") == []


def test_archiver_vide(tmp_path):
    assert "Rien" in Archive(tmp_path / "a.json").archiver("  ")


# --- Outils ---

def test_outils(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ARCHIVE_FILE", tmp_path / "a.json")
    a = Archive(tmp_path / "a.json")
    tools = {t.name: t for t in build_archive_tools(a)}
    assert set(tools) == {"archiver_note", "chercher_dans_memoire"}
    tools["archiver_note"].run(texte="le wifi invité s'appelle Jarvis_Guest", tags="wifi reseau")
    out = tools["chercher_dans_memoire"].run(sujet="comment s'appelle le wifi invité")
    assert "Jarvis_Guest" in out


def test_outil_rien_trouve(tmp_path):
    tools = {t.name: t for t in build_archive_tools(Archive(tmp_path / "a.json"))}
    assert "ne retrouve rien" in tools["chercher_dans_memoire"].run(sujet="licorne")
