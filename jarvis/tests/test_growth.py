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


# --- Auto-amélioration (le mentor écrit du code, en autonomie mais encadré) ---

def test_ameliorer_delegates_to_mentor_with_safety_policy(tmp_path):
    from types import SimpleNamespace as NS

    sent = {}
    agent = NS(delegate=lambda task: sent.__setitem__("task", task) or "J'ai créé outil.py et ses tests, tout passe.")
    j = journal(tmp_path)
    j.add("savoir jouer de la musique")
    tools = {t.name: t for t in build_growth_tools(j, agent=agent)}
    assert "ameliorer_jarvis" in tools
    out = tools["ameliorer_jarvis"].run(idee="")       # prend la plus demandée
    assert "tout passe" in out
    task = sent["task"]
    assert "savoir jouer de la musique" in task
    # La politique de sécurité est bien transmise au mentor :
    assert "Ne modifie AUCUN de ces fichiers" in task and "config.py" in task
    assert "n'affaiblis ni ne contournes JAMAIS une confirmation" in task
    assert "les tests passent" in task


def test_ameliorer_asks_confirmation(tmp_path):
    from types import SimpleNamespace as NS

    j = journal(tmp_path)
    tools = {t.name: t for t in build_growth_tools(j, agent=NS(delegate=lambda t: "ok"))}
    assert "valider" in tools["ameliorer_jarvis"].confirm()


def test_ameliorer_empty_journal(tmp_path):
    from types import SimpleNamespace as NS

    called = []
    agent = NS(delegate=lambda t: called.append(t) or "x")
    tools = {t.name: t for t in build_growth_tools(journal(tmp_path), agent=agent)}
    assert "vide" in tools["ameliorer_jarvis"].run(idee="")
    assert called == []                                # rien à faire, le mentor n'est pas sollicité


def test_no_ameliorer_tool_without_mentor(tmp_path):
    tools = {t.name: t for t in build_growth_tools(journal(tmp_path), agent=None)}
    assert "ameliorer_jarvis" not in tools             # pas de mentor = pas d'auto-amélioration
