"""Tests du banc d'essai avec un faux Ollama (vitesses et choix d'outils simulés)."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bench  # noqa: E402
import config  # noqa: E402

# Vitesses simulées (jetons/s) : la puce graphique va plus vite que le processeur.
SPEED = {"rapide:latest": {"gpu": 30.0, "cpu": 10.0}, "lent:latest": {"gpu": 8.0, "cpu": 4.0}}


class FakeOllama:
    def __init__(self, smart=("rapide:latest", "lent:latest")):
        self.smart = set(smart)
        self.calls = []

    def chat(self, model, messages, tools=None, options=None, **kwargs):
        model = model if ":" in model else f"{model}:latest"
        options = options or {}
        self.calls.append((model, options, kwargs))
        if tools:  # test des outils
            question = messages[-1]["content"]
            expected = next(e for q, e in bench.ROUTING_TESTS if q == question)
            name = expected if model in self.smart else "heure_et_date"
            calls = [{"function": {"name": name, "arguments": {}}}] if name else []
            return {"message": {"content": "", "tool_calls": calls}}
        n = options.get("num_predict", 1)
        speed = SPEED[model]["cpu" if options.get("num_gpu") == 0 else "gpu"]
        return {"message": {"content": "x"}, "eval_count": n, "eval_duration": n / speed * 1e9,
                "prompt_eval_duration": 0.5e9, "load_duration": 0}

    def ps(self):
        return NS(models=[NS(model=m, size=100, size_vram=100) for m in SPEED])


def test_variants_cover_gpu_and_cpu():
    names = [v.name for v in bench.variants(16)]
    assert names[0].startswith("auto")
    assert bench.variants(16)[1].options == {"num_gpu": 0, "num_thread": 8}
    assert bench.variants(16)[2].options == {"num_gpu": 0, "num_thread": 16}
    assert len(bench.variants(1)) == 2  # pas de doublon sur une machine à 1 cœur


def test_run_measures_speed_and_tools():
    client = FakeOllama()
    results = bench.run(client, ["rapide"], reps=2, cpu_count=8, log=lambda *a: None)
    by_variant = {r.variant: r for r in results}
    auto = by_variant["auto (puce graphique si possible)"]
    assert auto.tokens_per_s == pytest.approx(30.0)
    assert auto.gpu_percent == 100
    assert by_variant["processeur seul, 4 cœurs"].tokens_per_s == pytest.approx(10.0)
    assert auto.tools_score == auto.tools_total == len(bench.ROUTING_TESTS)
    assert auto.spoken_answer_s == pytest.approx(0.5 + 55 / 30, abs=0.01)


def test_tool_usage_beats_raw_speed():
    """Un modèle rapide mais qui se trompe d'outil ne doit pas gagner."""
    client = FakeOllama(smart=("lent:latest",))
    results = bench.run(client, ["rapide", "lent"], reps=1, cpu_count=4, log=lambda *a: None)
    best = bench.pick_best(results)
    assert best.model == "lent:latest" or best.model == "lent"
    assert best.tools_score == len(bench.ROUTING_TESTS)


def test_best_is_fastest_among_correct_models():
    results = bench.run(FakeOllama(), ["lent", "rapide"], reps=1, cpu_count=4, log=lambda *a: None)
    best = bench.pick_best(results)
    assert best.model == "rapide" and best.variant.startswith("auto")
    assert best.options == {}


def test_failed_model_is_reported_not_crashing():
    class Broken(FakeOllama):
        def chat(self, model, *a, **k):
            if model == "casse":
                raise RuntimeError("out of memory")
            return super().chat(model, *a, **k)

    results = bench.run(Broken(), ["casse", "rapide"], reps=1, cpu_count=4, log=lambda *a: None)
    assert results[0].error == "out of memory"
    assert bench.pick_best(results).model == "rapide"


def test_verdict_thresholds():
    assert bench.verdict(20) == "fluide"
    assert bench.verdict(8) == "correct"
    assert bench.verdict(3) == "trop lent pour l'oral"


def test_set_env_line_updates_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nJARVIS_MODELE_LOCAL=ancien\n", encoding="utf-8")
    bench.set_env_line(env, "JARVIS_MODELE_LOCAL", "qwen3:30b-a3b")
    bench.set_env_line(env, "JARVIS_OPTIONS_OLLAMA", '{"num_gpu":0}')
    assert env.read_text(encoding="utf-8") == (
        'A=1\nJARVIS_MODELE_LOCAL=qwen3:30b-a3b\nJARVIS_OPTIONS_OLLAMA={"num_gpu":0}\n')


def test_main_applies_best_config_after_confirmation(tmp_path, monkeypatch, capsys):
    import ollama

    fake = FakeOllama()
    fake.list = lambda: NS(models=[NS(model=m) for m in SPEED])
    monkeypatch.setattr(ollama, "Client", lambda host: fake)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LOCAL_MODEL", "lent")
    env = tmp_path / ".env"
    env.write_text("JARVIS_MODELE_LOCAL=lent\n", encoding="utf-8")
    monkeypatch.setattr(bench, "ENV_FILE", env)
    monkeypatch.setattr("builtins.input", lambda prompt="": "oui")
    monkeypatch.setattr(sys, "argv", ["bench.py", "--modeles", "lent,rapide", "--rapide", "--appliquer"])
    bench.main()
    assert "JARVIS_MODELE_LOCAL=rapide" in env.read_text(encoding="utf-8")
    report = next(tmp_path.glob("bench-*.json"))
    assert len(json.loads(report.read_text(encoding="utf-8"))) == 6  # 2 modèles × 3 variantes
    assert "Meilleure configuration : rapide" in capsys.readouterr().out


def test_brain_passes_tuned_options(tmp_path, monkeypatch):
    from brain import Brain
    from memory import Memory

    seen = {}

    class Client:
        def chat(self, model, messages, tools, **kwargs):
            seen.update(kwargs)
            return {"message": {"content": "ok"}}

    monkeypatch.setattr(config, "LOCAL_OPTIONS", {"num_gpu": 0, "num_thread": 8})
    Brain(Client(), {}, Memory(tmp_path / "m.json"), lambda d: True, model="t").reply("salut")
    assert seen["options"] == {"num_gpu": 0, "num_thread": 8}


def test_default_selection_is_current_plus_recommended_installed(tmp_path, monkeypatch, capsys):
    import ollama

    fake = FakeOllama()
    fake.list = lambda: NS(models=[NS(model="lent:latest"), NS(model="nomic-embed-text:latest")])
    monkeypatch.setattr(ollama, "Client", lambda host: fake)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "LOCAL_MODEL", "lent")
    monkeypatch.setattr(sys, "argv", ["bench.py", "--rapide"])
    bench.main()
    tested = {model for model, _, _ in fake.calls}
    assert tested == {"lent:latest"}  # pas le modèle d'embeddings, qui ne sait pas discuter
    assert "Non installés" in capsys.readouterr().out
