"""Tests du renfort Gemini (Google), avec un faux service (aucun réseau)."""

import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from claude_bridge import ClaudeBridge, GeminiBackend  # noqa: E402


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_KEY", "cle-test")
    monkeypatch.setattr(config, "GEMINI_MODEL", "gemini-2.5-flash")


def reply(text):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


def test_selected_by_config(monkeypatch):
    monkeypatch.setattr(config, "RENFORT", "gemini")
    monkeypatch.setattr(config, "OFFLINE", False)
    assert isinstance(ClaudeBridge().backend, GeminiBackend)


def test_available_needs_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_KEY", "")
    b = GeminiBackend()
    assert not b.available
    assert "GEMINI_API_KEY" in ClaudeBridge(b).ask("salut")


def test_ask_sends_prompt_and_reads_answer(key):
    captured = {}

    def request(body):
        captured.update(body)
        return reply("Bonjour Enes, voici ma réponse.")

    out = ClaudeBridge(GeminiBackend(request=request)).ask("Explique la relativité", "contexte")
    assert out == "Bonjour Enes, voici ma réponse."
    assert "Jarvis" in captured["system_instruction"]["parts"][0]["text"]
    assert "Contexte : contexte" in captured["contents"][0]["parts"][0]["text"]


def test_safety_block_and_empty(key):
    blocked = GeminiBackend(request=lambda b: {"promptFeedback": {"blockReason": "SAFETY"}})
    assert "préféré ne pas" in blocked.ask("?")
    empty = GeminiBackend(request=lambda b: {"candidates": []})
    assert "rien répondu" in empty.ask("?")


@pytest.mark.parametrize("code, expected", [
    (400, "clé Gemini est refusée"), (403, "clé Gemini est refusée"),
    (429, "surchargé"), (500, "erreur (500)"),
])
def test_http_errors(key, code, expected):
    def boom(body):
        raise urllib.error.HTTPError("u", code, "no", {}, None)

    assert expected in GeminiBackend(request=boom).ask("?")


def test_network_and_bad_json(key):
    def down(body):
        raise urllib.error.URLError("refused")

    assert "joindre Gemini" in GeminiBackend(request=down).ask("?")

    def garbage(body):
        raise ValueError("pas du json")

    assert "illisible" in GeminiBackend(request=garbage).ask("?")


def test_gemini_cannot_act_on_pc(key):
    assert "Claude Code" in GeminiBackend(request=lambda b: reply("x")).delegate("range mes photos")


def test_gemini_advisor_tool_coexists_with_claude(tmp_path, monkeypatch):
    """Claude ET Gemini en même temps : deux outils distincts."""
    import skills
    from tools import build_tools
    from types import SimpleNamespace as NS

    monkeypatch.setattr(config, "GEMINI_KEY", "cle-test")
    statuses = []
    gemini = GeminiBackend(request=lambda b: reply("Avis de Gemini."))
    claude = NS(available=True, ask=lambda q, c="": "Avis de Claude.")
    tools = build_tools(None, claude, statuses.append,
                        reminders=skills.Reminders(tmp_path / "r.json"),
                        lists=skills.Lists(tmp_path / "l.json"),
                        gemini=gemini)
    assert "demander_a_claude" in tools and "demander_a_gemini" in tools
    assert tools["demander_a_gemini"].run("salut") == "Avis de Gemini."
    assert any("Gemini" in s for s in statuses)


def test_no_gemini_tool_without_key(tmp_path, monkeypatch):
    import skills
    from tools import build_tools
    from types import SimpleNamespace as NS

    monkeypatch.setattr(config, "GEMINI_KEY", "")
    tools = build_tools(None, NS(available=True, ask=lambda q, c="": "x"), lambda s: None,
                        reminders=skills.Reminders(tmp_path / "r.json"),
                        lists=skills.Lists(tmp_path / "l.json"),
                        gemini=GeminiBackend())
    assert "demander_a_gemini" not in tools


# --- Abonnement Gemini (Gemini CLI) ---

from claude_bridge import GeminiCliBackend  # noqa: E402


class FakeRun:
    def __init__(self, returncode=0, stdout="Réponse de Gemini.", stderr=""):
        import subprocess
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.cmd = self.kwargs = None

    def __call__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        return self.result


def test_cli_selected_by_config(monkeypatch):
    monkeypatch.setattr(config, "RENFORT", "gemini-abonnement")
    monkeypatch.setattr(config, "OFFLINE", False)
    assert isinstance(ClaudeBridge().backend, GeminiCliBackend)


def test_cli_command_is_read_only_and_uses_subscription(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_CLI_MODEL", "")
    monkeypatch.setenv("GEMINI_API_KEY", "ne-doit-pas-servir")
    run = FakeRun()
    b = GeminiCliBackend(runner=run, which=lambda n: "/usr/local/bin/gemini")
    assert ClaudeBridge(b).ask("Ton avis ?", "ctx") == "Réponse de Gemini."
    cmd = run.cmd
    assert cmd[0] == "/usr/local/bin/gemini" and "-p" in cmd
    assert cmd[cmd.index("--approval-mode") + 1] == "plan"   # lecture seule : il n'agit pas
    assert "-y" not in cmd and "--yolo" not in cmd
    assert "Ton avis ?" in run.kwargs["input"] and "Contexte : ctx" in run.kwargs["input"]
    assert "GEMINI_API_KEY" not in run.kwargs["env"]         # abonnement, pas la clé
    assert "GOOGLE_API_KEY" not in run.kwargs["env"]


def test_cli_not_installed_and_not_logged_in():
    assert "pas installé" in ClaudeBridge(GeminiCliBackend(which=lambda n: None)).ask("?")
    b = GeminiCliBackend(runner=FakeRun(1, "", "Please sign in to your Google account"),
                         which=lambda n: "gemini")
    assert "pas connecté" in ClaudeBridge(b).ask("?")


def test_cli_cannot_act_on_pc():
    b = GeminiCliBackend(runner=FakeRun(), which=lambda n: "gemini")
    assert "Claude Code" in ClaudeBridge(b).delegate("range mes photos")
