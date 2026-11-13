"""Tests du journal des améliorations de Jarvis."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from growth import GrowthJournal, build_growth_tools  # noqa: E402


def journal(tmp_path):
    return GrowthJournal(tmp_path / "ameliorations.json")


def test_add_and_list(tmp_path):
    j = journal(tmp_path)
    assert "noté" in j.add("savoir lire mes mails")
    assert "savoir lire mes mails" in j.text()


def test_duplicate_increments_counter(tmp_path):
    j = journal(tmp_path)
    j.add("piloter la musique")
    assert "revient" in j.add("Piloter la musique")   # insensible à la casse
    assert j.pending()[0]["compteur"] == 2


def test_most_requested_first(tmp_path):
    j = journal(tmp_path)
    j.add("A")
    j.add("B")
    for _ in range(3):
        j.add("B")
    assert j.pending()[0]["idee"] == "B"             # B redemandé le plus


def test_empty_and_blank(tmp_path):
    j = journal(tmp_path)
    assert "vide" in j.text()
    assert "une idée" in j.add("   ")


def test_mark_done_removes_from_pending(tmp_path):
    j = journal(tmp_path)
    j.add("tâche faite")
    assert j.mark_done("tâche faite") is True
    assert "vide" in j.text()
    assert j.mark_done("inconnue") is False


def test_persists_on_disk(tmp_path):
    journal(tmp_path).add("se souvenir de mes rendez-vous")
    j2 = GrowthJournal(tmp_path / "ameliorations.json")
    assert "rendez-vous" in j2.text()


def test_tools(tmp_path):
    j = journal(tmp_path)
    tools = {t.name: t for t in build_growth_tools(j)}
    assert tools["noter_a_ameliorer"].run(idee="voler en autonomie").startswith("C'est noté")
    assert "voler en autonomie" in tools["journal_ameliorations"].run()
    assert tools["noter_a_ameliorer"].confirm is None   # juste noter : pas de confirmation
