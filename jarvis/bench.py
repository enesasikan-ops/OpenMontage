"""Banc d'essai : trouve la configuration la plus rapide de Jarvis SUR CET ORDINATEUR.

    python bench.py                         # ton modèle actuel + les modèles conseillés déjà installés
    python bench.py --modeles qwen3:30b-a3b,qwen3:8b
    python bench.py --rapide                # 1 essai par configuration au lieu de 3
    python bench.py --appliquer             # propose d'enregistrer la meilleure config dans .env

Pour chaque modèle, il mesure :
- la vitesse de parole (mots-jetons par seconde) avec la puce graphique, puis sur
  le processeur seul avec différents nombres de cœurs ;
- le délai avant le premier mot ;
- s'il utilise correctement les outils de Jarvis (heure, mémoire, appel à Claude).
Rien n'est modifié sans ton accord.
"""

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import config  # noqa: E402
from brain import system_prompt  # noqa: E402
from memory import Memory  # noqa: E402
from tools import build_tools  # noqa: E402

ENV_FILE = Path(__file__).parent / ".env"

# Modèles essayés s'ils sont installés (du plus gros au plus petit).
CANDIDATES = ["qwen3:30b-a3b", "mistral-small3.2", "qwen3:14b", "qwen3:8b", "llama3.1:8b"]

SPEECH_PROMPT = ("Explique-moi en cinq ou six phrases simples comment fonctionne "
                 "une pompe à chaleur, comme si tu me parlais.")
MAX_TOKENS = 150
SPOKEN_ANSWER_TOKENS = 55  # une réponse orale typique (~2 phrases)

# (question, outil attendu) — None = doit répondre sans outil.
ROUTING_TESTS = [
    ("Salut Jarvis, ça va ?", None),
    ("Quelle heure est-il ?", "heure_et_date"),
    ("Retiens que mon chat s'appelle Gribouille.", "retenir"),
    ("Rappelle-moi dans 20 minutes de sortir le linge.", "rappeler"),
    ("Combien font 1 250 fois 18 % ?", "calculer"),
    ("Ajoute du lait à la liste de courses.", "ajouter_a_la_liste"),
    ("Fais-moi un rapport de sécurité.", "rapport_securite"),
    ("Allume la lumière du salon.", "allumer"),
    ("Demande à Claude de m'expliquer la relativité générale en détail.", "demander_a_claude"),
    ("Rédige-moi un business plan complet pour ouvrir une boulangerie.", "demander_a_claude"),
]


@dataclass
class Variant:
    name: str
    options: dict = field(default_factory=dict)


@dataclass
class Result:
    model: str
    variant: str
    options: dict
    tokens_per_s: float
    first_word_s: float
    spoken_answer_s: float
    tools_score: int
    tools_total: int
    gpu_percent: int | None = None
    load_s: float | None = None
    error: str | None = None


def variants(cpu_count: int) -> list[Variant]:
    half = max(1, cpu_count // 2)
    out = [Variant("auto (puce graphique si possible)", {})]
    out.append(Variant(f"processeur seul, {half} cœurs", {"num_gpu": 0, "num_thread": half}))
    if cpu_count != half:
        out.append(Variant(f"processeur seul, {cpu_count} cœurs", {"num_gpu": 0, "num_thread": cpu_count}))
    return out


def _f(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def _extra() -> dict:
    return {} if config.LOCAL_THINK is None else {"think": config.LOCAL_THINK}


def measure_speed(client, model: str, options: dict, reps: int) -> tuple[float, float]:
    """Renvoie (jetons/seconde, secondes avant le premier mot), médianes."""
    opts = {**options, "temperature": 0, "seed": 1}
    # Échauffement : changer de réglage recharge le modèle, on ne veut pas le mesurer.
    client.chat(model=model, messages=[{"role": "user", "content": "Bonjour"}],
                options={**opts, "num_predict": 1}, **_extra())
    speeds, firsts = [], []
    for _ in range(reps):
        r = client.chat(model=model, messages=[{"role": "user", "content": SPEECH_PROMPT}],
                        options={**opts, "num_predict": MAX_TOKENS}, **_extra())
        eval_s = (_f(r, "eval_duration") or 0) / 1e9
        speeds.append((_f(r, "eval_count") or 0) / eval_s if eval_s else 0.0)
        firsts.append(((_f(r, "prompt_eval_duration") or 0) + (_f(r, "load_duration") or 0)) / 1e9)
    return statistics.median(speeds), statistics.median(firsts)


def routing_score(client, model: str, options: dict) -> tuple[int, list[str]]:
    """Vérifie que le modèle choisit le bon outil. Les outils ne sont PAS exécutés."""

    class NoClaude:
        available = True

        def ask(self, *a, **k):
            return ""

    with tempfile.TemporaryDirectory() as tmp:
        from security import Sentinel
        from skills import Lists, Reminders

        memory = Memory(Path(tmp) / "m.json")
        tools = build_tools(memory, NoClaude(), on_status=lambda s: None,
                            reminders=Reminders(Path(tmp) / "r.json"), lists=Lists(Path(tmp) / "l.json"),
                            sentinel=Sentinel(Path(tmp) / "s.json"))
        schemas = [t.schema() for t in tools.values()]
        system = system_prompt(memory)

    score, details = 0, []
    for question, expected in ROUTING_TESTS:
        r = client.chat(model=model, tools=schemas,
                        messages=[{"role": "system", "content": system},
                                  {"role": "user", "content": question}],
                        options={**options, "temperature": 0, "seed": 1, "num_predict": 200},
                        **_extra())
        calls = _f(_f(r, "message"), "tool_calls") or []
        used = _f(_f(calls[0], "function"), "name") if calls else None
        ok = used == expected
        score += ok
        details.append(f"{'✅' if ok else '❌'} « {question} » → {used or 'répond seul'}"
                       + ("" if ok else f" (attendu : {expected or 'répond seul'})"))
    return score, details


def gpu_percent(client, model: str) -> int | None:
    try:
        full = model if ":" in model else f"{model}:latest"
        for m in client.ps().models:
            if _f(m, "model", "") == full and _f(m, "size"):
                return round(100 * (_f(m, "size_vram") or 0) / _f(m, "size"))
    except Exception:
        return None
    return None


def verdict(tokens_per_s: float) -> str:
    if tokens_per_s >= 12:
        return "fluide"
    if tokens_per_s >= 6:
        return "correct"
    return "trop lent pour l'oral"


def pick_best(results: list[Result]) -> Result | None:
    ok = [r for r in results if r.error is None]
    if not ok:
        return None
    best_tools = max(r.tools_score for r in ok)
    # D'abord le bon usage des outils (sinon Jarvis est inutilisable), ensuite la vitesse.
    return max((r for r in ok if r.tools_score == best_tools),
               key=lambda r: (r.tokens_per_s, -r.first_word_s))


def set_env_line(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(client, models: list[str], reps: int, cpu_count: int, log=print) -> list[Result]:
    results: list[Result] = []
    for model in models:
        log(f"\n🧠 {model}")
        try:
            t0 = time.monotonic()
            client.chat(model=model, messages=[{"role": "user", "content": "Bonjour"}],
                        options={"num_predict": 1}, **_extra())
            load_s = time.monotonic() - t0
            log(f"   Chargement : {load_s:.1f} s")
            score, details = routing_score(client, model, {})
            log(f"   Usage des outils : {score}/{len(ROUTING_TESTS)}")
            for d in details:
                log(f"     {d}")
        except Exception as exc:
            log(f"   ⚠️ Impossible de tester ce modèle : {exc}")
            results.append(Result(model, "-", {}, 0, 0, 0, 0, len(ROUTING_TESTS), error=str(exc)))
            continue

        for v in variants(cpu_count):
            try:
                speed, first = measure_speed(client, model, v.options, reps)
            except Exception as exc:
                log(f"   ⚠️ {v.name} : échec ({exc})")
                continue
            gpu = gpu_percent(client, model) if not v.options else None
            spoken = first + (SPOKEN_ANSWER_TOKENS / speed if speed else float("inf"))
            gpu_txt = f", {gpu} % sur la puce graphique" if gpu is not None else ""
            log(f"   {v.name:<36} {speed:5.1f} jetons/s, 1er mot {first:4.1f} s, "
                f"réponse orale ≈ {spoken:4.1f} s → {verdict(speed)}{gpu_txt}")
            results.append(Result(model, v.name, v.options, round(speed, 2), round(first, 2),
                                  round(spoken, 2), score, len(ROUTING_TESTS), gpu, round(load_s, 1)))
    return results


def main() -> None:
    import ollama

    parser = argparse.ArgumentParser(description="Banc d'essai de Jarvis")
    parser.add_argument("--modeles", help="liste séparée par des virgules (sinon : modèle actuel + modèles conseillés installés)")
    parser.add_argument("--rapide", action="store_true", help="1 essai par configuration")
    parser.add_argument("--appliquer", action="store_true",
                        help="propose d'enregistrer la meilleure configuration dans .env")
    args = parser.parse_args()

    client = ollama.Client(host=config.OLLAMA_HOST)
    try:
        installed = {m.model for m in client.list().models}
    except Exception:
        sys.exit("❌ Ollama ne répond pas. Ouvre l'app Ollama puis relance.")

    def norm(name: str) -> str:
        return name if ":" in name else f"{name}:latest"

    wanted = args.modeles.split(",") if args.modeles else [config.LOCAL_MODEL, *CANDIDATES]
    models = list(dict.fromkeys(m.strip() for m in wanted if norm(m.strip()) in installed))
    missing = [m for m in CANDIDATES if norm(m) not in installed]
    if not models:
        sys.exit("❌ Aucun modèle à tester. Installe-en un, par ex. : ollama pull qwen3:8b")

    cpu = os.cpu_count() or 4
    reps = 1 if args.rapide else 3
    print(f"Banc d'essai Jarvis — {cpu} cœurs logiques, {len(models)} modèle(s), {reps} essai(s) "
          "par configuration. Compte quelques minutes par modèle.")
    if missing and not args.modeles:
        print("ℹ️  Non installés (pour les tester aussi : ollama pull <nom>) : " + ", ".join(missing))

    results = run(client, models, reps, cpu)
    best = pick_best(results)

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    report = config.DATA_DIR / f"bench-{datetime.now():%Y%m%d-%H%M}.json"
    report.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n📄 Rapport complet : {report}")

    if best is None:
        sys.exit("❌ Aucune configuration n'a fonctionné.")
    print(f"\n🏆 Meilleure configuration : {best.model} — {best.variant}")
    print(f"   {best.tokens_per_s} jetons/s ({verdict(best.tokens_per_s)}), "
          f"réponse orale ≈ {best.spoken_answer_s} s, outils {best.tools_score}/{best.tools_total}")
    if best.tools_score < best.tools_total:
        print("   ⚠️ Ce modèle se trompe parfois d'outil : un modèle plus gros ferait mieux.")

    options = json.dumps(best.options, separators=(",", ":")) if best.options else ""
    print("\nRéglages correspondants pour .env :")
    print(f"   JARVIS_MODELE_LOCAL={best.model}")
    print(f"   JARVIS_OPTIONS_OLLAMA={options}")
    if args.appliquer:
        if input("\nEnregistrer ces réglages dans .env ? (O/N) ").strip().lower() in ("o", "oui", "y", "yes"):
            set_env_line(ENV_FILE, "JARVIS_MODELE_LOCAL", best.model)
            set_env_line(ENV_FILE, "JARVIS_OPTIONS_OLLAMA", options)
            print("✅ Enregistré. Relance Jarvis pour en profiter.")
        else:
            print("Rien n'a été modifié.")


if __name__ == "__main__":
    main()
