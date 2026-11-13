"""Tests de Jarvis sans Ollama ni clé API (modèles simulés)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from brain import Brain  # noqa: E402
from claude_bridge import ApiBackend, ClaudeBridge, NoBackend, SubscriptionBackend  # noqa: E402
from memory import Memory  # noqa: E402
from tools import build_tools  # noqa: E402


class FakeOllama:
    """Rejoue une liste de réponses prédéfinies, comme le ferait Ollama."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, model, messages, tools):
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        return {"message": self.replies.pop(0)}


def tool_call(name, **args):
    return {"content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def text(content):
    return {"content": content}


class FakeClaude:
    available = True

    def __init__(self):
        self.questions = []

    def ask(self, question, context=""):
        self.questions.append(question)
        return "Réponse de Claude."


@pytest.fixture
def memory(tmp_path):
    return Memory(tmp_path / "memoire.json")


def make_brain(replies, memory, claude=None, confirm=lambda d: True):
    statuses = []
    tools = build_tools(memory, claude or FakeClaude(), on_status=statuses.append)
    brain = Brain(FakeOllama(replies), tools, memory, confirm, model="test")
    return brain, statuses


def test_simple_question_answered_locally(memory):
    brain, statuses = make_brain([text("Salut !")], memory)
    assert brain.reply("Salut Jarvis") == "Salut !"
    assert statuses == []


def test_hard_question_escalates_to_claude(memory):
    claude = FakeClaude()
    brain, statuses = make_brain(
        [tool_call("demander_a_claude", question="Explique la relativité"),
         text("Réponse de Claude.")],
        memory, claude,
    )
    assert brain.reply("Explique-moi la relativité") == "Réponse de Claude."
    assert claude.questions == ["Explique la relativité"]
    assert statuses and "Claude" in statuses[0]
    tool_msg = brain.history[-2]
    assert tool_msg == {"role": "tool", "tool_name": "demander_a_claude", "content": "Réponse de Claude."}


def test_time_tool_returns_date(memory):
    brain, _ = make_brain([tool_call("heure_et_date"), text("Il est l'heure.")], memory)
    brain.reply("Quelle heure est-il ?")
    assert "il est" in brain.history[-2]["content"]


def test_remember_persists_to_disk(memory, tmp_path):
    brain, _ = make_brain([tool_call("retenir", fait="Enes aime le café serré"), text("Noté.")], memory)
    brain.reply("Retiens que j'aime le café serré")
    assert Memory(tmp_path / "memoire.json").facts == ["Enes aime le café serré"]
    # La mémoire est injectée dans les instructions du tour suivant.
    brain.client.replies.append(text("ok"))
    brain.reply("et sinon ?")
    assert "café serré" in brain.client.calls[-1]["messages"][0]["content"]


def test_sensitive_action_needs_confirmation(memory):
    memory.remember("Code du garage : 1234")
    asked = []

    def refuse(description):
        asked.append(description)
        return False

    brain, _ = make_brain([tool_call("oublier", mot_cle="garage"), text("D'accord, j'annule.")],
                          memory, confirm=refuse)
    brain.reply("Oublie le code du garage")
    assert asked and "garage" in asked[0]
    assert memory.facts == ["Code du garage : 1234"]  # rien n'a été supprimé
    assert "refusé" in brain.history[-2]["content"]


def test_confirmed_action_runs(memory):
    memory.remember("Code du garage : 1234")
    brain, _ = make_brain([tool_call("oublier", mot_cle="garage"), text("C'est oublié.")], memory)
    brain.reply("Oublie le code du garage")
    assert memory.facts == []


def test_unknown_tool_and_bad_args_do_not_crash(memory):
    brain, _ = make_brain([tool_call("pirater_la_nasa"), tool_call("retenir"), text("Oups.")], memory)
    assert brain.reply("fais un truc") == "Oups."
    assert "inconnu" in brain.history[2]["content"]
    assert "invalides" in brain.history[4]["content"]


def test_tool_loop_is_bounded(memory):
    brain, _ = make_brain([tool_call("heure_et_date")] * 20, memory)
    assert "reformuler" in brain.reply("boucle")


def test_api_backend_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    answer = ClaudeBridge(ApiBackend()).ask("test")
    assert "ANTHROPIC_API_KEY" in answer and "mes propres moyens" in answer


def test_no_backend_stays_local():
    bridge = ClaudeBridge(NoBackend())
    assert not bridge.available
    assert "100 % local" in bridge.ask("test")


class FakeRun:
    def __init__(self, returncode=0, stdout="Réponse abonnement.", stderr=""):
        self.result = subprocess.CompletedProcess([], returncode, stdout, stderr)
        self.kwargs = None
        self.cmd = None

    def __call__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        return self.result


def test_subscription_backend_calls_claude_code_safely(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ne-doit-pas-servir")
    run = FakeRun()
    backend = SubscriptionBackend(runner=run, which=lambda name: "/usr/local/bin/claude")
    assert ClaudeBridge(backend).ask("Question", "ctx") == "Réponse abonnement."
    assert run.cmd[:2] == ["claude", "-p"]
    assert run.cmd[run.cmd.index("--tools") + 1] == ""      # aucun outil
    assert "--no-session-persistence" in run.cmd
    assert "--bare" not in run.cmd                           # --bare interdit la connexion par abonnement
    assert "Question" not in " ".join(run.cmd)               # la question passe par stdin
    assert "Question" in run.kwargs["input"]
    assert "ANTHROPIC_API_KEY" not in run.kwargs["env"]      # sinon ce serait facturé à l'API
    assert run.kwargs["cwd"] == str(tmp_path)


def test_subscription_backend_not_installed():
    backend = SubscriptionBackend(runner=FakeRun(), which=lambda name: None)
    assert "Claude Code n'est pas installé" in ClaudeBridge(backend).ask("?")


@pytest.mark.parametrize("stderr, expected", [
    ("Invalid API key · Please run /login", "pas connecté"),
    ("Claude usage limit reached", "limite de ton abonnement"),
    ("boom", "problème"),
])
def test_subscription_backend_errors(stderr, expected):
    backend = SubscriptionBackend(runner=FakeRun(returncode=1, stdout="", stderr=stderr),
                                  which=lambda name: "claude")
    assert expected in ClaudeBridge(backend).ask("?")


def test_subscription_backend_timeout():
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    backend = SubscriptionBackend(runner=slow, which=lambda name: "claude")
    assert "trop de temps" in ClaudeBridge(backend).ask("?")


def test_bridge_sends_expected_request():
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text="Bonjour Enes.")],
        )

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    assert ClaudeBridge(ApiBackend(client=fake)).ask("Salut", "contexte") == "Bonjour Enes."
    assert captured["model"] == "claude-opus-5-5"
    assert captured["fallbacks"] == "default"
    assert "Contexte : contexte" in captured["messages"][0]["content"]


def test_bridge_handles_refusal():
    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        create=lambda **k: SimpleNamespace(stop_reason="refusal", content=[]))))
    assert "préféré ne pas" in ClaudeBridge(ApiBackend(client=fake)).ask("?")


def test_voice_yes_detection():
    voice = pytest.importorskip("voice")
    assert voice.is_yes("Oui vas-y")
    assert voice.is_yes("ok")
    assert not voice.is_yes("non surtout pas")
    assert not voice.is_yes("attends")
