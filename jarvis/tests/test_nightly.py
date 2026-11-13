"""Tests de l'amélioration de nuit : le mentor code, Jarvis annonce le matin, tu valides."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import growth  # noqa: E402
from growth import GrowthJournal, NightlyImprover, Proposals, load_plugins  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")

PLUGIN_CODE = '''from tools import Tool


def build_tools():
    return [Tool(name="dire_bonjour_turc", description="Dit bonjour en turc.",
                 parameters={"type": "object", "properties": {}, "required": []},
                 run=lambda: "Merhaba !")]
'''
PLUGIN_TEST = '''def test_ok():
    assert True
'''


class FakeMentor:
    """Écrit pour de vrai un petit module + son test dans le dossier demandé."""

    def __init__(self, write=True):
        self.tasks = []
        self.write = write

    def delegate(self, task):
        self.tasks.append(task)
        folder = Path(task.split("Dossier de travail à utiliser (et uniquement lui) : ")[1].split("\n")[0])
        if self.write:
            (folder / "bonjour_turc.py").write_text(PLUGIN_CODE, encoding="utf-8")
            (folder / "test_bonjour_turc.py").write_text(PLUGIN_TEST, encoding="utf-8")
        return "J'ai créé bonjour_turc.py et son test."


class Clock:
    def __init__(self, hour, minute=0):
        self.t = datetime(2026, 11, 14, hour, minute, tzinfo=PARIS)

    def __call__(self):
        return self.t


def setup(tmp_path, hour=3, mentor=None, tester=None):
    journal = GrowthJournal(tmp_path / "j.json")
    journal.add("dire bonjour en turc")
    props = Proposals(journal, plugins_dir=tmp_path / "plugins",
                      tester=tester or (lambda folder: (True, "1 passed")))
    sent = []
    clock = Clock(hour)
    imp = NightlyImprover(journal, props, mentor or FakeMentor(), at="03:00",
                          notify=lambda text, pid: sent.append((text, pid)),
                          workspace=tmp_path / "atelier", now=clock,
                          quiet=lambda now: 22 <= now.hour or now.hour < 7)
    return journal, props, imp, sent, clock


def test_night_work_then_morning_announcement(tmp_path):
    journal, props, imp, sent, clock = setup(tmp_path, hour=3)
    imp.tick()                                   # 3h : le mentor code
    assert len(props.pending()) == 1
    assert sent == []                            # la nuit : silence
    clock.t = clock.t.replace(hour=8)
    imp.tick()                                   # 8h : annonce
    assert len(sent) == 1
    text, pid = sent[0]
    assert "dire bonjour en turc" in text and "tests passent" in text and pid == 1
    imp.tick()
    assert len(sent) == 1                        # annoncé une seule fois


def test_only_once_per_night_and_not_before_time(tmp_path):
    _, props, imp, _, clock = setup(tmp_path, hour=2)
    imp.tick()
    assert props.pending() == []                 # 2h : trop tôt
    clock.t = clock.t.replace(hour=3, minute=5)
    imp.tick()
    imp.tick()
    assert len(props.items) == 1                 # une seule proposition par nuit


def test_safety_policy_sent_to_mentor(tmp_path):
    mentor = FakeMentor()
    _, _, imp, _, _ = setup(tmp_path, mentor=mentor)
    imp.tick()
    task = mentor.tasks[0]
    assert "Ne modifie AUCUN de ces fichiers" in task
    assert "build_tools()" in task and "dire bonjour en turc" in task


def test_activate_copies_plugin_and_loads_it(tmp_path):
    journal, props, imp, _, _ = setup(tmp_path, tester=growth.run_tests)
    imp.tick()                                   # vrais tests pytest sur le code écrit
    p = props.pending()[0]
    assert p["tests_ok"] is True
    out = props.activate(p["id"])
    assert "activée" in out
    assert (tmp_path / "plugins" / "dire_bonjour_en_turc" / "bonjour_turc.py").exists()
    loaded = {t.name: t for t in load_plugins(tmp_path / "plugins")}
    assert loaded["dire_bonjour_turc"].run() == "Merhaba !"   # nouvelle capacité utilisable
    assert "vide" in journal.text()              # l'idée est marquée comme faite


def test_activation_refused_if_tests_fail(tmp_path):
    _, props, imp, _, _ = setup(tmp_path, tester=lambda folder: (False, "1 failed"))
    imp.tick()
    out = props.activate(1)
    assert "ne passent pas" in out
    assert not (tmp_path / "plugins").exists()


def test_activation_refused_if_core_file_touched(tmp_path):
    _, props, imp, _, _ = setup(tmp_path)
    imp.tick()
    folder = Path(props.items[0]["dossier"])
    (folder / "config.py").write_text("PIRATE = True", encoding="utf-8")
    assert "cœur" in props.activate(1)


def test_reject(tmp_path):
    journal, props, imp, _, _ = setup(tmp_path)
    imp.tick()
    assert "abandonne" in props.reject(1)
    assert props.pending() == []
    assert "dire bonjour en turc" in journal.text()   # l'idée reste dans la liste
    assert "pas d'amélioration" in props.activate(1)


def test_broken_plugin_is_ignored(tmp_path):
    bad = tmp_path / "plugins" / "casse"
    bad.mkdir(parents=True)
    (bad / "casse.py").write_text("raise RuntimeError('boum')", encoding="utf-8")
    assert load_plugins(tmp_path / "plugins") == []   # ne fait pas tomber Jarvis


def test_mentor_failure_does_not_crash(tmp_path):
    class Boom:
        def delegate(self, task):
            raise RuntimeError("quota")

    _, props, imp, _, _ = setup(tmp_path, mentor=Boom())
    imp.tick()                                   # ne doit pas lever
    assert props.pending() == []


def test_proposal_tools(tmp_path):
    _, props, imp, _, _ = setup(tmp_path)
    imp.tick()
    tools = {t.name: t for t in growth.build_proposal_tools(props)}
    assert "n°1" in tools["ameliorations_a_valider"].run()
    assert "confirmes" in tools["activer_amelioration"].confirm(numero=1)
    assert tools["rejeter_amelioration"].confirm is None


def test_telegram_buttons_activate(tmp_path):
    import pytest

    pytest.importorskip("telegram")
    from telegram_bot import TelegramJarvis

    _, props, imp, _, _ = setup(tmp_path)
    imp.tick()
    jarvis = TelegramJarvis(lambda c, s: None, 42)
    jarvis.proposals = props
    edited = []

    async def answer(*a, **k):
        pass

    async def edit(text):
        edited.append(text)

    query = NS(data="rej:1", answer=answer, edit_message_text=edit, message=NS(text="🌙 annonce"))
    asyncio.run(jarvis.on_button(NS(effective_user=NS(id=42), callback_query=query), NS()))
    assert "abandonne" in edited[0]
