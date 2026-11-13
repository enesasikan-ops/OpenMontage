"""Tests des compétences : rappels, calcul, météo, listes, état du PC."""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import skills  # noqa: E402
from brain import Brain  # noqa: E402
from memory import Memory  # noqa: E402
from tools import build_tools  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


class Clock:
    def __init__(self):
        self.t = datetime(2026, 11, 13, 10, 0, tzinfo=PARIS)

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def reminders(tmp_path, clock):
    return skills.Reminders(tmp_path / "rappels.json", now=clock)


# --- Rappels ---

def test_reminder_in_minutes_fires_once(reminders, clock):
    assert "aujourd'hui à 10h20" in reminders.add("sortir le linge", dans_minutes=20)
    assert reminders.pop_due() == []
    clock.advance(minutes=21)
    assert reminders.pop_due() == ["sortir le linge"]
    assert reminders.pop_due() == []


def test_reminder_at_date_and_tomorrow_wording(reminders):
    answer = reminders.add("appeler le dentiste", date_heure="2026-11-14 08:30")
    assert "demain à 8h30" in answer
    assert "n°1" in reminders.list_text()


def test_reminder_rejects_past_and_garbage(reminders):
    assert "déjà passé" in reminders.add("x", date_heure="2026-11-13 09:00")
    assert "illisible" in reminders.add("x", date_heure="demain matin")
    assert "illisible" in reminders.add("x", dans_minutes="bientôt")
    assert "Il me faut" in reminders.add("x")
    assert reminders.list_text() == "Aucun rappel en attente."


def test_reminders_survive_restart(tmp_path, clock):
    skills.Reminders(tmp_path / "r.json", now=clock).add("payer le loyer", dans_minutes=5)
    clock.advance(minutes=6)
    assert skills.Reminders(tmp_path / "r.json", now=clock).pop_due() == ["payer le loyer"]


def test_cancel_reminder(reminders):
    reminders.add("a", dans_minutes=5)
    assert reminders.cancel(1) == "Rappel n°1 annulé."
    assert "pas de rappel" in reminders.cancel(1)
    assert "illisible" in reminders.cancel("le premier")


def test_watcher_thread_notifies(reminders, clock):
    got = []
    reminders.add("thé", dans_minutes=1)
    watcher = skills.ReminderWatcher(reminders, notify=got.append, interval_s=0.02)
    watcher.start()
    clock.advance(minutes=2)
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.02)
    watcher.stop()
    watcher.join(2)
    assert got == ["⏰ Rappel : thé"] and not watcher.is_alive()


def test_watcher_survives_failing_notify(reminders, clock):
    def boom(text):
        raise RuntimeError("réseau coupé")

    reminders.add("a", dans_minutes=1)
    clock.advance(minutes=2)
    skills.ReminderWatcher(reminders, notify=boom).tick()  # ne doit pas lever


# --- Calcul ---

@pytest.mark.parametrize("expression, expected", [
    ("1250 * 0.2", "250"), ("15% * 80", "12"), ("3,5 + 1,5", "5"), ("sqrt(144)", "12"),
    ("2^10", "1024"), ("10 / 4", "2,5"), ("max(3, 7)", "7"), ("12 × 3", "36"),
])
def test_calculate(expression, expected):
    assert skills.calculate(expression).endswith(f"= {expected}")


@pytest.mark.parametrize("expression", [
    "__import__('os').system('echo pirate')", "open('/etc/passwd').read()", "9**9**9",
    "(1).__class__", "x + 1", "",
])
def test_calculate_refuses_code_and_bombs(expression):
    assert "Je ne sais pas calculer" in skills.calculate(expression)


def test_calculate_division_by_zero():
    assert "zéro" in skills.calculate("1/0")


# --- Météo ---

def fake_fetch(url):
    if "geocoding" in url:
        assert "name=Lyon" in url
        return {"results": [{"name": "Lyon", "latitude": 45.75, "longitude": 4.85}]}
    assert "latitude=45.75" in url
    return {"current": {"temperature_2m": 11.6, "weather_code": 61, "wind_speed_10m": 14.2},
            "daily": {"weather_code": [61, 3], "temperature_2m_max": [13.1, 15.4],
                      "temperature_2m_min": [7.2, 8.0], "precipitation_probability_max": [80, 20]}}


def test_weather_summary():
    text = skills.weather("Lyon", fetch=fake_fetch)
    assert "À Lyon : 12 degrés, pluie faible, vent 14 km/h" in text
    assert "Demain : couvert, de 8 à 15 degrés, 20 % de risque de pluie" in text


def test_weather_unknown_city_network_error_and_offline(monkeypatch):
    assert "ne trouve pas" in skills.weather("Xyzzy", fetch=lambda url: {})

    def down(url):
        raise OSError("pas de réseau")

    assert "n'arrive pas" in skills.weather("Lyon", fetch=down)
    monkeypatch.setattr(config, "CITY", "")
    assert "quelle ville" in skills.weather("", fetch=fake_fetch)
    monkeypatch.setattr(config, "OFFLINE", True)
    assert "hors ligne" in skills.weather("Lyon", fetch=fake_fetch)


# --- Listes ---

def test_lists(tmp_path):
    lists = skills.Lists(tmp_path / "l.json")
    assert "Ajouté" in lists.add("Lait")
    assert "déjà" in lists.add("lait")
    lists.add("Pain")
    lists.add("Dune 3", liste="Films")
    assert lists.read() == "Liste courses : Lait, Pain"
    assert "Retiré de la liste courses : Lait" == lists.remove("lait")
    assert "ne trouve pas" in lists.remove("caviar")
    assert skills.Lists(tmp_path / "l.json").read("films") == "Liste films : Dune 3"
    assert "Listes existantes : courses, films" in lists.read("idées")


# --- État du PC ---

def test_pc_status_reads_real_machine():
    text = skills.pc_status()
    assert "Disque :" in text and "Mémoire :" in text and "Processeur :" in text


@pytest.mark.parametrize("payload, expected", [
    ({"AntivirusEnabled": True, "RealTimeProtectionEnabled": True, "AntivirusSignatureAge": 0}, "actif et à jour"),
    ({"AntivirusEnabled": True, "RealTimeProtectionEnabled": False, "AntivirusSignatureAge": 0}, "désactivée"),
    ({"AntivirusEnabled": True, "RealTimeProtectionEnabled": True, "AntivirusSignatureAge": 9}, "9 jours"),
])
def test_defender_status_on_windows(monkeypatch, payload, expected):
    monkeypatch.setattr(skills.platform, "system", lambda: "Windows")
    run = lambda *a, **k: NS(stdout=json.dumps(payload))  # noqa: E731
    assert expected in skills._defender_status(run)


def test_defender_status_failure_and_non_windows(monkeypatch):
    monkeypatch.setattr(skills.platform, "system", lambda: "Windows")

    def broken(*a, **k):
        raise FileNotFoundError("powershell")

    assert "inconnu" in skills._defender_status(broken)
    monkeypatch.setattr(skills.platform, "system", lambda: "Darwin")
    assert skills._defender_status(broken) == ""


# --- Intégration avec le cerveau ---

def test_brain_uses_skills_end_to_end(tmp_path, clock):
    memory = Memory(tmp_path / "m.json")
    reminders = skills.Reminders(tmp_path / "r.json", now=clock)
    lists = skills.Lists(tmp_path / "l.json")
    tools = build_tools(memory, NS(available=False), lambda s: None, reminders=reminders, lists=lists)
    assert {"rappeler", "calculer", "meteo", "lire_liste", "etat_du_pc"} <= set(tools)

    replies = [
        {"content": "", "tool_calls": [{"function": {"name": "rappeler", "arguments": {
            "message": "sortir le linge", "dans_minutes": 20}}}]},
        {"content": "C'est noté."},
        {"content": "", "tool_calls": [{"function": {"name": "calculer", "arguments": {"expression": "1250*0.18"}}}]},
        {"content": "Ça fait 225."},
    ]

    class Client:
        def chat(self, model, messages, tools, **kwargs):
            return {"message": replies.pop(0)}

    brain = Brain(Client(), tools, memory, lambda d: True, model="t")
    brain.reply("Rappelle-moi dans 20 minutes de sortir le linge")
    assert "Rappel n°1 programmé" in brain.history[-2]["content"]
    brain.reply("Combien font 1250 fois 18 % ?")
    assert brain.history[-2]["content"].endswith("= 225")
    clock.advance(minutes=25)
    assert reminders.pop_due() == ["sortir le linge"]


def test_fetch_retries_once_on_network_glitch(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def urlopen(request, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("handshake timed out")
        return Response()

    monkeypatch.setattr(skills.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(skills.time, "sleep", lambda s: None)
    assert skills._fetch_json("https://exemple.test") == {"ok": True}
    assert len(calls) == 2
