"""Tests de la navigation web et du mode mentor (agent supervisé)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import web  # noqa: E402
from claude_bridge import ClaudeBridge, NoBackend, SubscriptionBackend  # noqa: E402
from tools import build_tools  # noqa: E402

RESULTS = [
    {"title": "SNCF Connect", "body": "Paris–Lyon en 1h57, dès 29€.", "href": "https://www.sncf-connect.com/trains"},
    {"title": "Horaires TGV", "body": "Départs toutes les heures.", "href": "https://trainline.fr/x"},
]


# --- Recherche web ---

def test_search_formats_results(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    out = web.search("train paris lyon", searcher=lambda q, n: RESULTS)
    assert "Paris–Lyon en 1h57" in out and "sncf-connect.com" in out
    assert "trainline.fr" in out


def test_search_offline_empty_and_error(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", True)
    assert "hors ligne" in web.search("x", searcher=lambda q, n: RESULTS)
    monkeypatch.setattr(config, "OFFLINE", False)
    assert "cherche" in web.search("  ", searcher=lambda q, n: RESULTS)
    assert "rien trouvé" in web.search("abcdef", searcher=lambda q, n: [])

    def boom(q, n):
        raise RuntimeError("réseau")

    assert "n'arrive pas" in web.search("x", searcher=boom)


def test_search_handles_alternative_keys(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    alt = [{"title": "T", "snippet": "extrait", "url": "https://exemple.fr/p"}]
    assert "extrait" in web.search("x", searcher=lambda q, n: alt)


# --- Lecture de page ---

def test_read_page_strips_html(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    html = "<html><head><style>b{}</style></head><body><h1>Titre</h1><script>x()</script><p>Bonjour &amp; bienvenue.</p></body></html>"
    out = web.read_page("exemple.fr", fetch=lambda url: html)
    assert "Titre Bonjour & bienvenue." in out
    assert "x()" not in out and "<" not in out


def test_read_page_truncates(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    big = "<p>" + "mot " * 2000 + "</p>"
    out = web.read_page("https://exemple.fr", fetch=lambda url: big)
    assert len(out) <= web.PAGE_CHARS + 1 and out.endswith("…")


def test_read_page_errors_and_offline(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", True)
    assert "hors ligne" in web.read_page("exemple.fr", fetch=lambda u: "x")
    monkeypatch.setattr(config, "OFFLINE", False)

    def boom(url):
        raise OSError("404")

    assert "n'arrive pas" in web.read_page("exemple.fr", fetch=boom)


# --- Mode mentor (agent) ---

class FakeRun:
    def __init__(self, returncode=0, stdout="J'ai créé le script dans l'atelier.", stderr=""):
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.cmd = self.kwargs = None

    def __call__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        return self.result


def test_agent_command_is_confined_and_tooled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE", tmp_path / "atelier")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ne-doit-pas-servir")
    run = FakeRun()
    backend = SubscriptionBackend(runner=run, which=lambda n: "/usr/local/bin/claude")
    out = ClaudeBridge(backend).delegate("écris un script qui range mes photos")
    assert out == "J'ai créé le script dans l'atelier."
    cmd = run.cmd
    assert "--add-dir" in cmd and str(tmp_path / "atelier") in cmd
    assert "Bash" in cmd and "Write" in cmd          # de vrais outils, cette fois
    assert cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in cmd  # jamais
    assert "écris un script" in run.kwargs["input"]     # la tâche passe par stdin
    assert run.kwargs["cwd"] == str(tmp_path / "atelier")
    assert "ANTHROPIC_API_KEY" not in run.kwargs["env"]  # abonnement, pas l'API


def test_agent_timeout_and_errors():
    def slow(cmd, **k):
        raise subprocess.TimeoutExpired(cmd, 1)

    b = SubscriptionBackend(runner=slow, which=lambda n: "claude")
    assert "trop de temps" in ClaudeBridge(b).delegate("x")
    b2 = SubscriptionBackend(runner=FakeRun(1, "", "usage limit reached"), which=lambda n: "claude")
    assert "limite" in ClaudeBridge(b2).delegate("x")


def test_agent_needs_subscription():
    assert "Claude Code" in ClaudeBridge(NoBackend()).delegate("x") or \
           "désactivé" in ClaudeBridge(NoBackend()).delegate("x")


def test_mentor_tool_registered_only_when_enabled(tmp_path):
    import skills

    agent = NS(delegate=lambda task: f"fait : {task}")
    statuses = []
    tools = build_tools(None, NS(available=False), statuses.append,
                        reminders=skills.Reminders(tmp_path / "r.json"),
                        lists=skills.Lists(tmp_path / "l.json"), agent=agent)
    assert "confier_a_claude" in tools and "chercher_sur_le_web" in tools
    tool = tools["confier_a_claude"]
    assert "confier à Claude" in tool.confirm("ranger mes photos")
    assert tool.run("ranger mes photos") == "fait : ranger mes photos"
    assert statuses and "mentor" in statuses[0]
    # sans agent : pas d'outil mentor, mais le web reste
    plain = build_tools(None, NS(available=False), lambda t: None,
                        reminders=skills.Reminders(tmp_path / "r2.json"),
                        lists=skills.Lists(tmp_path / "l2.json"))
    assert "confier_a_claude" not in plain and "chercher_sur_le_web" in plain


def test_mentor_action_goes_through_confirmation(tmp_path):
    import skills
    from brain import Brain

    calls = []
    agent = NS(delegate=lambda task: calls.append(task) or "C'est fait.")
    tools = build_tools(None, NS(available=False), lambda t: None,
                        reminders=skills.Reminders(tmp_path / "r.json"),
                        lists=skills.Lists(tmp_path / "l.json"), agent=agent)

    replies = [{"content": "", "tool_calls": [{"function": {"name": "confier_a_claude",
                                               "arguments": {"tache": "écris un script"}}}]},
               {"content": "C'est fait, Monsieur."}]

    class Client:
        def chat(self, model, messages, tools, **k):
            return {"message": replies.pop(0)}

    # L'utilisateur refuse : rien ne doit être confié à Claude.
    from memory import Memory
    brain = Brain(Client(), tools, Memory(tmp_path / "m.json"), confirm=lambda d: False, model="t")
    brain.reply("écris-moi un script")
    assert calls == [] and "refusé" in brain.history[-2]["content"]
