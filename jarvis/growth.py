"""Le journal des améliorations de Jarvis — comment il progresse, de façon encadrée.

Principe (amélioration continue, mais sûre) :
1. Quand Jarvis ne sait pas faire quelque chose, il l'écrit ici (outil noter_a_ameliorer).
2. Plus tard, Claude (le mentor) lit ce journal et écrit la nouvelle capacité, AVEC des tests.
3. L'utilisateur relit et valide avant que ça entre dans Jarvis.
4. Jarvis sait alors faire la nouvelle chose : ce qui était impossible devient possible.

Jarvis ne réécrit JAMAIS son propre code tout seul : chaque amélioration passe par des
tests et par ton accord. Ce fichier est la liste de souhaits, pas un exécuteur.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config


class GrowthJournal:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.data = {"idees": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, idee: str, origine: str = "manuel") -> str:
        idee = idee.strip()
        if not idee:
            return "Il me faut une idée à noter."
        now = datetime.now(ZoneInfo(config.TIMEZONE))
        for e in self.data["idees"]:
            if e["idee"].lower() == idee.lower() and not e.get("fait"):
                e["compteur"] = e.get("compteur", 1) + 1  # déjà demandé : on compte
                self._save()
                return "C'était déjà dans ma liste d'améliorations, je note que ça revient."
        self.data["idees"].append({"idee": idee, "origine": origine, "fait": False,
                                   "compteur": 1, "date": now.date().isoformat()})
        self._save()
        return f"C'est noté dans ma liste d'améliorations : {idee}. On pourra l'ajouter plus tard."

    def pending(self) -> list[dict]:
        # Les plus redemandées d'abord.
        return sorted((e for e in self.data["idees"] if not e.get("fait")),
                      key=lambda e: e.get("compteur", 1), reverse=True)

    def mark_done(self, idee: str) -> bool:
        for e in self.data["idees"]:
            if e["idee"].lower() == idee.strip().lower():
                e["fait"] = True
                self._save()
                return True
        return False

    def text(self) -> str:
        pend = self.pending()
        if not pend:
            return "Ma liste d'améliorations est vide pour l'instant."
        lignes = []
        for e in pend:
            fois = f" (demandé {e['compteur']} fois)" if e.get("compteur", 1) > 1 else ""
            lignes.append(f"- {e['idee']}{fois}")
        return "Idées d'amélioration en attente :\n" + "\n".join(lignes)


# Fichiers sensibles que l'auto-amélioration ne doit JAMAIS modifier (sécurité en dur).
PROTECTED = ("config.py", "claude_bridge.py", "drone.py", "security.py", "brain.py",
             "main.py", "telegram_bot.py", "tools.py", ".env")

# Consigne donnée au mentor (Claude Code) pour qu'il code une amélioration en autonomie,
# mais sans jamais toucher au cœur sensible ni retirer les confirmations.
SELF_IMPROVE_POLICY = """Tu ajoutes une NOUVELLE capacité à Jarvis, en autonomie, dans l'atelier.
Règles de sécurité STRICTES (non négociables) :
- Crée un NOUVEAU fichier pour la capacité (ex. atelier/<nom>.py) et SES TESTS (pytest).
- Pour partir d'un squelette propre, utilise le générateur : écris une config YAML
  (voir `python -m scaffold exemple jarvis-capacite`) puis `python -m scaffold generer`,
  et complète uniquement les zones « manuel ».
- Ne modifie AUCUN de ces fichiers du cœur : """ + ", ".join(PROTECTED) + """.
- Ne retire, n'affaiblis ni ne contournes JAMAIS une confirmation : toute action qui
  envoie, supprime, pilote, paie ou ouvre quelque chose doit demander confirmation.
- N'ajoute pas d'accès réseau caché, pas de collecte de données, rien qui sorte en douce.
- Écris des tests qui prouvent que ça marche, lance-les, et ne considère la tâche finie
  que si les tests passent.
- Termine par un résumé court en français : ce que tu as créé, où, et le résultat des tests.
Jarvis n'intègre rien tout seul : l'utilisateur relira et validera avant activation."""


def build_growth_tools(journal: GrowthJournal, agent=None) -> list:
    from tools import Tool

    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    tools = [
        Tool(name="noter_a_ameliorer",
             description=("Note une capacité qui manque à Jarvis, pour l'ajouter plus tard. "
                          "À utiliser quand tu ne sais pas faire quelque chose, ou quand "
                          "l'utilisateur dit « tu devrais pouvoir... », « ce serait bien que tu saches... »."),
             parameters=obj({"idee": {**s, "description": "La capacité manquante, en une phrase."}}, ["idee"]),
             run=lambda idee: journal.add(idee, origine="jarvis")),
        Tool(name="journal_ameliorations",
             description="Liste les améliorations en attente (ce que Jarvis ne sait pas encore faire).",
             parameters=obj({}, []),
             run=lambda: journal.text()),
    ]

    if agent is not None:
        def ameliorer(idee: str = "") -> str:
            idee = idee.strip()
            if not idee:
                pend = journal.pending()
                if not pend:
                    return "Ma liste d'améliorations est vide, il n'y a rien à ajouter."
                idee = pend[0]["idee"]
            task = (f"{SELF_IMPROVE_POLICY}\n\nLa capacité à ajouter : {idee}")
            return agent.delegate(task)

        tools.append(Tool(
            name="ameliorer_jarvis",
            description=("Demande au mentor (Claude) d'ÉCRIRE une nouvelle capacité de Jarvis en "
                         "autonomie, avec ses tests, dans l'atelier. Prend l'idée donnée, ou la plus "
                         "demandée du journal. Le code n'est PAS activé : tu le relis et valides après."),
            parameters=obj({"idee": {**s, "description": "La capacité à coder (vide = la plus demandée)."}}, []),
            run=ameliorer,
            confirm=lambda idee="": ("Je vais demander à Claude d'écrire cette capacité (code + tests) "
                                     "dans l'atelier, sans toucher au cœur de Jarvis. On la validera avant "
                                     "de l'activer. OK ?")))
    return tools


# =====================================================================================
# Amélioration de nuit : le mentor code pendant que tu dors, tu valides le matin.
# =====================================================================================

import importlib.util  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from datetime import time as dtime  # noqa: E402
from typing import Callable  # noqa: E402

log = logging.getLogger("jarvis.amelioration")

PLUGINS_DIR = Path(__file__).parent / "plugins"
TEST_TIMEOUT_S = 300


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (s or "capacite")[:40]


def proposal_task(idee: str, folder: Path) -> str:
    return (f"{SELF_IMPROVE_POLICY}\n\n"
            f"Dossier de travail à utiliser (et uniquement lui) : {folder}\n"
            "Le module Python que tu crées doit exposer une fonction `build_tools()` qui renvoie une "
            "liste d'objets `tools.Tool` (from tools import Tool), pour que Jarvis le charge comme "
            "extension. Les tests vont dans le même dossier, dans des fichiers test_*.py.\n\n"
            f"La capacité à ajouter : {idee}")


def run_tests(folder: Path, run: Callable = subprocess.run) -> tuple[bool, str]:
    """Lance les tests d'une proposition. (réussite, résumé)"""
    if not any(folder.glob("test_*.py")):
        return False, "aucun test écrit"
    try:
        out = run([sys.executable, "-m", "pytest", "-q", str(folder)], capture_output=True,
                  text=True, timeout=TEST_TIMEOUT_S, cwd=str(Path(__file__).parent))
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"tests impossibles à lancer ({exc})"
    last = (out.stdout or "").strip().splitlines()[-1:] or [""]
    return out.returncode == 0, last[0]


class Proposals:
    """Améliorations codées par le mentor, en attente de ta décision. Stockées dans le journal."""

    def __init__(self, journal: GrowthJournal, plugins_dir: Path = PLUGINS_DIR,
                 tester: Callable = run_tests):
        self.journal = journal
        self.plugins_dir = plugins_dir
        self.tester = tester
        self.journal.data.setdefault("propositions", [])

    @property
    def items(self) -> list[dict]:
        return self.journal.data["propositions"]

    def add(self, idee: str, folder: Path, resume: str, tests_ok: bool, tests: str) -> dict:
        pid = max((p["id"] for p in self.items), default=0) + 1
        p = {"id": pid, "idee": idee, "dossier": str(folder), "resume": resume.strip()[:1500],
             "tests_ok": tests_ok, "tests": tests, "statut": "proposé", "annoncé": False}
        self.items.append(p)
        self.journal._save()
        return p

    def get(self, pid) -> "dict | None":
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return None
        return next((p for p in self.items if p["id"] == pid), None)

    def pending(self) -> list[dict]:
        return [p for p in self.items if p["statut"] == "proposé"]

    def announcement(self, p: dict) -> str:
        etat = "les tests passent ✅" if p["tests_ok"] else f"⚠️ les tests ne passent pas ({p['tests']})"
        return (f"🌙 Cette nuit, j'ai travaillé sur : {p['idee']}.\n{p['resume']}\n"
                f"Résultat : {etat}.\nAmélioration n°{p['id']} — tu l'actives ?")

    def activate(self, pid) -> str:
        p = self.get(pid)
        if p is None or p["statut"] != "proposé":
            return f"Je n'ai pas d'amélioration n°{pid} en attente."
        folder = Path(p["dossier"])
        ok, summary = self.tester(folder)
        if not ok:
            return f"Je n'active pas l'amélioration n°{p['id']} : les tests ne passent pas ({summary})."
        files = [f for f in folder.glob("*.py")]
        if not files:
            return "Cette proposition ne contient aucun fichier de code."
        if any(f.name in PROTECTED for f in files):
            return "Je refuse : la proposition touche à un fichier du cœur de Jarvis."
        dest = self.plugins_dir / _slug(p["idee"])
        dest.mkdir(parents=True, exist_ok=True)
        for f in files:
            shutil.copy2(f, dest / f.name)
        p["statut"], p["plugin"] = "activé", str(dest)
        self.journal.mark_done(p["idee"])
        self.journal._save()
        return (f"Amélioration n°{p['id']} activée ({summary}). Relance Jarvis pour qu'il "
                f"l'utilise : il saura désormais « {p['idee']} ».")

    def reject(self, pid) -> str:
        p = self.get(pid)
        if p is None or p["statut"] != "proposé":
            return f"Je n'ai pas d'amélioration n°{pid} en attente."
        p["statut"] = "rejeté"
        self.journal._save()
        return f"D'accord, j'abandonne l'amélioration n°{p['id']}. L'idée reste dans ma liste."

    def list_text(self) -> str:
        pend = self.pending()
        if not pend:
            return "Aucune amélioration en attente de validation."
        return "En attente de ta validation :\n" + "\n".join(
            f"- n°{p['id']} : {p['idee']} ({'tests OK' if p['tests_ok'] else 'tests en échec'})"
            for p in pend)


class NightlyImprover(threading.Thread):
    """Chaque nuit à l'heure choisie : le mentor code l'idée la plus demandée.
    Le matin (hors heures de silence), Jarvis te l'annonce et tu valides."""

    def __init__(self, journal: GrowthJournal, proposals: Proposals, agent,
                 notify: Callable[[str, int], None], at: str = "",
                 workspace: Path = None, now: Callable = None, interval_s: float = 60,
                 quiet: Callable = None):
        super().__init__(daemon=True, name="jarvis-amelioration-nuit")
        self.journal, self.proposals, self.agent, self.notify = journal, proposals, agent, notify
        self.at = at if at is not None else ""
        self.workspace = workspace or config.WORKSPACE
        if now is None:
            from skills import _now as now
        self.now = now
        if quiet is None:
            from proactive import in_quiet_hours as quiet
        self.quiet = quiet
        self.interval_s = interval_s
        self._halt = threading.Event()

    def _due(self, now) -> bool:
        try:
            h, m = (int(x) for x in self.at.split(":"))
        except (ValueError, AttributeError):
            return False
        if self.journal.data.get("derniere_nuit") == now.date().isoformat():
            return False
        return (now.hour, now.minute) >= (h, m) and now.time() < dtime(h, m).replace(hour=min(h + 4, 23))

    def work(self, now) -> "dict | None":
        """Code l'idée la plus demandée. Renvoie la proposition créée (ou None)."""
        self.journal.data["derniere_nuit"] = now.date().isoformat()
        self.journal._save()
        pend = [e for e in self.journal.pending()
                if not any(p["idee"] == e["idee"] and p["statut"] == "proposé"
                           for p in self.proposals.items)]
        if not pend:
            return None
        idee = pend[0]["idee"]
        folder = self.workspace / "propositions" / f"{now:%Y%m%d}_{_slug(idee)}"
        folder.mkdir(parents=True, exist_ok=True)
        resume = self.agent.delegate(proposal_task(idee, folder))
        ok, tests = self.proposals.tester(folder)
        return self.proposals.add(idee, folder, resume, ok, tests)

    def announce(self, now) -> None:
        if self.quiet(now):
            return
        for p in self.proposals.pending():
            if not p.get("annoncé"):
                p["annoncé"] = True
                self.journal._save()
                self.notify(self.proposals.announcement(p), p["id"])

    def tick(self) -> None:
        now = self.now()
        try:
            if self._due(now):
                self.work(now)
            self.announce(now)
        except Exception as exc:  # une nuit ratée ne doit pas arrêter Jarvis
            log.warning("amélioration de nuit : %s", exc)

    def run(self) -> None:
        while not self._halt.is_set():
            self.tick()
            self._halt.wait(self.interval_s)

    def stop(self) -> None:
        self._halt.set()


def load_plugins(plugins_dir: Path = PLUGINS_DIR) -> list:
    """Charge les capacités validées (plugins/*/*.py exposant build_tools()). Une extension
    cassée est ignorée, elle ne fait jamais tomber Jarvis."""
    tools = []
    if not plugins_dir.exists():
        return tools
    for path in sorted(plugins_dir.glob("*/*.py")):
        if path.name.startswith("test_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"jarvis_plugin_{path.parent.name}_{path.stem}", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "build_tools"):
                tools += list(module.build_tools())
        except Exception as exc:
            log.warning("extension ignorée (%s) : %s", path, exc)
    return tools


def build_proposal_tools(proposals: Proposals) -> list:
    from tools import Tool

    num = {"type": "integer", "description": "Le numéro de l'amélioration."}
    obj = lambda props, req: {"type": "object", "properties": props, "required": req}  # noqa: E731
    return [
        Tool(name="activer_amelioration",
             description="Active une amélioration codée par le mentor (après ses tests). « active l'amélioration 3 ».",
             parameters=obj({"numero": num}, ["numero"]), run=proposals.activate,
             confirm=lambda numero: f"J'active l'amélioration n°{numero} dans Jarvis. Tu confirmes ?"),
        Tool(name="rejeter_amelioration",
             description="Abandonne une amélioration proposée.",
             parameters=obj({"numero": num}, ["numero"]), run=proposals.reject),
        Tool(name="ameliorations_a_valider",
             description="Liste les améliorations codées qui attendent ta validation.",
             parameters=obj({}, []), run=lambda: proposals.list_text()),
    ]
