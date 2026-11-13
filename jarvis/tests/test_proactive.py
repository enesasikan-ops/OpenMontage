"""Tests des initiatives : briefing du matin, alertes, heures de silence."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import proactive  # noqa: E402
import skills  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


class Clock:
    def __init__(self, hour=8, minute=0):
        self.t = datetime(2026, 11, 13, hour, minute, tzinfo=PARIS)

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROACTIVE_FILE", tmp_path / "initiatives.json")
    monkeypatch.setattr(config, "BRIEFING_TIME", "08:00")
    monkeypatch.setattr(config, "QUIET_HOURS", "22:00-07:00")
    monkeypatch.setattr(config, "ALERTS", True)
    monkeypatch.setattr(config, "CITY", "Lyon")
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "TITLE", "Monsieur")
    return tmp_path


def make(env, clock, alerts=None, weather="À Lyon : 12 degrés, pluie faible."):
    sent = []
    state = {"alerts": alerts or {}}
    reminders = skills.Reminders(env / "r.json", now=clock)
    lists = skills.Lists(env / "l.json")
    p = proactive.Proactive(reminders, lists, notify=sent.append, now=clock,
                            weather=lambda: weather, alerts=lambda: dict(state["alerts"]))
    return p, sent, reminders, lists, state


def test_morning_briefing_content_and_only_once(env):
    clock = Clock(8, 5)
    p, sent, reminders, lists, _ = make(env, clock)
    reminders.add("appeler le dentiste", date_heure="2026-11-13 14:30")
    reminders.add("demain, pas aujourd'hui", date_heure="2026-11-14 09:00")
    lists.add("lait")
    lists.add("pain")
    p.tick()
    p.tick()
    assert len(sent) == 1
    text = sent[0]
    assert text.startswith("Bonjour Monsieur. Voici votre point du jour.")
    assert "À Lyon : 12 degrés" in text
    assert "appeler le dentiste à 14h30" in text and "demain, pas" not in text
    assert "La liste de courses compte 2 articles." in text
    assert "L'ordinateur se porte bien." in text


def test_briefing_not_before_time_and_skipped_if_too_late(env):
    clock = Clock(7, 30)
    p, sent, *_ = make(env, clock)
    p.tick()
    assert sent == []
    clock.t = clock.t.replace(hour=20)   # PC allumé le soir : pas de « bonjour » à 20 h
    p.tick()
    assert sent == []


def test_briefing_given_once_across_two_processes(env):
    clock = Clock(8, 1)
    a, sent_a, *_ = make(env, clock)
    b, sent_b, *_ = make(env, clock)     # ex. mode vocal + bot Telegram
    a.tick()
    b.tick()
    assert len(sent_a) == 1 and sent_b == []


def test_briefing_disabled_and_resumes_next_day(env, monkeypatch):
    clock = Clock(8, 1)
    p, sent, *_ = make(env, clock)
    monkeypatch.setattr(config, "BRIEFING_TIME", "")
    p.tick()
    assert sent == []
    monkeypatch.setattr(config, "BRIEFING_TIME", "08:00")
    p.tick()
    clock.t += timedelta(days=1)
    p.tick()
    assert len(sent) == 2


def test_briefing_mentions_problems_and_no_duplicate_alert(env):
    clock = Clock(8, 1)
    p, sent, *_ = make(env, clock, alerts={"antivirus": "la protection antivirus en temps réel est désactivée"})
    p.tick()
    assert "À signaler : la protection antivirus" in sent[0]
    clock.t += timedelta(hours=2)
    p.tick()                              # déjà dit dans le briefing : pas de doublon
    assert len(sent) == 1


def test_alert_sent_once_per_day(env):
    clock = Clock(15, 0)
    p, sent, _, _, state = make(env, clock)
    p.tick()
    assert sent == []                     # tout va bien : silence
    state["alerts"] = {"disque": "le disque est presque plein, il ne reste que 12 Go"}
    clock.t += timedelta(hours=1, minutes=1)
    p.tick()
    assert sent == ["Pardonnez l'interruption, Monsieur, mais le disque est presque plein, il ne reste que 12 Go."]
    clock.t += timedelta(hours=2)
    p.tick()
    assert len(sent) == 1                 # pas de rabâchage le même jour
    clock.t += timedelta(days=1)
    p.tick()
    assert len(sent) == 2                 # toujours pas réglé le lendemain : il le redit


def test_alerts_checked_at_most_hourly_and_can_be_disabled(env, monkeypatch):
    clock = Clock(15, 0)
    calls = []
    p, sent, *_ = make(env, clock)
    p.alerts = lambda: calls.append(1) or {}
    for _ in range(5):
        p.tick()
        clock.t += timedelta(minutes=1)
    assert len(calls) == 1
    monkeypatch.setattr(config, "ALERTS", False)
    clock.t += timedelta(hours=2)
    p.tick()
    assert len(calls) == 1


def test_quiet_hours_block_everything(env):
    clock = Clock(23, 30)
    p, sent, _, _, state = make(env, clock, alerts={"disque": "plein"})
    p.tick()
    assert sent == []
    clock.t = clock.t.replace(hour=3)
    p.tick()
    assert sent == []


@pytest.mark.parametrize("hour, spec, expected", [
    (23, "22:00-07:00", True), (3, "22:00-07:00", True), (7, "22:00-07:00", False),
    (12, "22:00-07:00", False), (13, "12:00-14:00", True), (15, "12:00-14:00", False),
    (3, "", False), (3, "n'importe quoi", False),
])
def test_in_quiet_hours(hour, spec, expected, monkeypatch):
    monkeypatch.setattr(config, "QUIET_HOURS", spec)
    assert proactive.in_quiet_hours(Clock(hour)()) is expected


def test_failing_source_does_not_crash(env):
    clock = Clock(8, 1)
    p, sent, *_ = make(env, clock)

    def boom():
        raise OSError("disque illisible")

    p.alerts = boom
    p.tick()                              # ne doit pas lever
    assert sent == []


def test_briefing_without_city_or_offline_skips_weather(env, monkeypatch):
    clock = Clock(8, 1)
    monkeypatch.setattr(config, "CITY", "")
    p, sent, *_ = make(env, clock)
    p.tick()
    assert "Lyon" not in sent[0] and "Aucun rappel prévu aujourd'hui." in sent[0]


def test_pc_alerts_on_real_machine_returns_dict():
    assert isinstance(skills.pc_alerts(), dict)


def test_thread_starts_and_stops(env):
    clock = Clock(8, 1)
    p, sent, *_ = make(env, clock)
    p.interval_s = 0.02
    p.start()
    import time
    deadline = time.time() + 3
    while not sent and time.time() < deadline:
        time.sleep(0.02)
    p.stop()
    p.join(2)
    assert len(sent) == 1 and not p.is_alive()
