"""Gestionnaire de plugins à chargement à chaud (hot-reload), couplé au générateur de code.

Les capacités métier vivent dans plugins/<nom>/*.py et exposent `build_tools()`.
Le gestionnaire surveille ce dossier et, SANS redémarrer Jarvis :
  - charge un plugin qui apparaît (généré par scaffold, activé par le mentor, copié à la main) ;
  - recharge un plugin dont le code change ;
  - décharge un plugin supprimé (en appelant son `on_unload()` s'il en a un).

Garanties :
  - Isolation : un plugin cassé (erreur d'import, build_tools qui plante, outil invalide)
    n'est PAS chargé, et la version précédente qui marchait reste en place (rollback).
  - Le cœur garde la priorité : un plugin ne peut pas remplacer un outil du cœur (refusé).
  - Atomicité : la liste d'outils du cerveau est remplacée d'un bloc, jamais modifiée sur
    place — une réponse en cours ne voit jamais une liste à moitié chargée.
  - Pas de boucle d'erreurs : une version cassée n'est retentée que si le fichier change.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tools import Tool

log = logging.getLogger("jarvis.plugins")

PLUGINS_DIR = Path(__file__).parent / "plugins"
JARVIS_ROOT = Path(__file__).parent
NAME_RE = re.compile(r"[a-z][a-z0-9_]*")


@dataclass
class PluginRecord:
    name: str
    signature: str
    tools: list[Tool]
    modules: list = field(default_factory=list)
    version: str = ""


def _sources(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.py") if not p.name.startswith("test_"))


def signature(folder: Path) -> str:
    """Empreinte du contenu du plugin (fichiers de code, hors tests)."""
    h = hashlib.sha1()
    for p in _sources(folder):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


class PluginError(Exception):
    pass


def _public_functions(module) -> dict:
    """Fonctions publiques DÉFINIES dans le module (pas importées, pas « _privées »)."""
    import inspect

    return {name: obj for name, obj in vars(module).items()
            if inspect.isfunction(obj) and not name.startswith("_")
            and obj.__module__ == module.__name__ and name not in ("build_tools", "on_unload")}


class PluginManager:
    def __init__(self, plugins_dir: Path = PLUGINS_DIR, core_names=frozenset(),
                 interval_s: float = 2.0):
        self.dir = Path(plugins_dir)
        self.core_names = frozenset(core_names)
        self.interval_s = interval_s
        self.loaded: dict[str, PluginRecord] = {}
        self.errors: dict[str, str] = {}
        self._failed: dict[str, str] = {}          # plugin -> empreinte de la version cassée
        self._listeners: list[Callable[[dict], None]] = []
        self._lock = threading.RLock()
        self._halt = threading.Event()
        self._thread: threading.Thread | None = None
        self._counter = 0

    # --- Chargement d'un plugin ---------------------------------------------------------------

    def _import(self, path: Path):
        self._counter += 1
        modname = f"jarvis_plugin_{path.parent.name}_{path.stem}_{self._counter}"
        spec = importlib.util.spec_from_file_location(modname, path)
        module = importlib.util.module_from_spec(spec)
        # On compile la SOURCE directement, sans le cache de bytecode (__pycache__) : sinon une
        # modification rapide de même taille peut recharger l'ancienne version (cache périmé).
        code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
        sys.path.insert(0, str(path.parent))        # imports entre fichiers du même plugin
        try:
            exec(code, module.__dict__)  # noqa: S102 (code des plugins locaux, comme un import)
        finally:
            sys.path.remove(str(path.parent))
            for sibling in _sources(path.parent):   # les fichiers voisins seront relus au prochain chargement
                if sibling != path:
                    sys.modules.pop(sibling.stem, None)
        sys.modules[modname] = module
        return module

    def _load(self, folder: Path, taken: set[str]) -> PluginRecord:
        if not NAME_RE.fullmatch(folder.name):
            raise PluginError("nom de dossier invalide (minuscules, chiffres et _)")
        tools, modules, version = [], [], ""
        for path in _sources(folder):
            try:
                module = self._import(path)
            except Exception as exc:
                raise PluginError(f"{path.name} : erreur au chargement ({exc.__class__.__name__}: {exc})") from exc
            modules.append(module)
            meta = getattr(module, "PLUGIN", {})
            version = str(meta.get("version", version)) if isinstance(meta, dict) else version
            if hasattr(module, "build_tools"):
                try:
                    built = list(module.build_tools())
                except Exception as exc:
                    raise PluginError(f"{path.name} : build_tools() a échoué ({exc})") from exc
                tools += built
        if not tools and not any(_public_functions(m) for m in modules):
            raise PluginError("rien à charger : ni build_tools(), ni fonction publique")
        names = []
        for t in tools:
            if not isinstance(t, Tool):
                raise PluginError(f"build_tools() doit renvoyer des Tool, pas {type(t).__name__}")
            if t.name in self.core_names:
                raise PluginError(f"l'outil « {t.name} » existe déjà dans le cœur de Jarvis")
            if t.name in taken or t.name in names:
                raise PluginError(f"l'outil « {t.name} » est déjà fourni par un autre plugin")
            names.append(t.name)
        return PluginRecord(folder.name, signature(folder), tools, modules, version)

    @staticmethod
    def _unload(record: PluginRecord) -> None:
        for module in record.modules:
            hook = getattr(module, "on_unload", None)
            if callable(hook):
                try:
                    hook()
                except Exception as exc:
                    log.warning("on_unload de %s : %s", record.name, exc)
            sys.modules.pop(module.__name__, None)

    # --- Synchronisation avec le dossier ------------------------------------------------------

    def reload(self) -> dict:
        """Compare le dossier à l'état chargé et applique les différences. Renvoie un rapport."""
        report = {"charges": [], "recharges": [], "decharges": [], "erreurs": {}}
        with self._lock:
            present = {}
            if self.dir.exists():
                for folder in sorted(p for p in self.dir.iterdir() if p.is_dir()):
                    if _sources(folder):
                        present[folder.name] = folder
            for name in sorted(set(self.loaded) - set(present)):
                self._unload(self.loaded.pop(name))
                self.errors.pop(name, None)
                report["decharges"].append(name)
            for name in sorted(set(self._failed) - set(present)):
                self._failed.pop(name)
                self.errors.pop(name, None)
            for name, folder in present.items():
                sig = signature(folder)
                current = self.loaded.get(name)
                if current and current.signature == sig:
                    continue
                if self._failed.get(name) == sig:
                    continue                     # même version cassée : on ne réessaie pas
                taken = {t.name for n, r in self.loaded.items() if n != name for t in r.tools}
                try:
                    record = self._load(folder, taken)
                except PluginError as exc:
                    self._failed[name] = sig
                    self.errors[name] = str(exc)
                    report["erreurs"][name] = str(exc)
                    log.warning("plugin %s non chargé : %s%s", name, exc,
                                " (l'ancienne version reste active)" if current else "")
                    continue
                if current:
                    self._unload(current)
                    report["recharges"].append(name)
                else:
                    report["charges"].append(name)
                self.loaded[name] = record
                self._failed.pop(name, None)
                self.errors.pop(name, None)
            changed = report["charges"] or report["recharges"] or report["decharges"]
            if changed:
                snapshot = self.tools()
                for listener in list(self._listeners):
                    listener(snapshot)
        if changed:
            log.info("plugins : %s", self.summary(report))
        return report

    # --- API directe : enregistrer du code et appeler ses fonctions ----------------------

    def save_and_load(self, plugin_name: str, source_code: str, file_name: str = "") -> PluginRecord:
        """Enregistre `source_code` dans plugins/<plugin_name>/ et le charge à chaud.

        Tout ou rien : si le code ne compile pas ou ne se charge pas, rien n'est modifié —
        ni sur le disque, ni en mémoire — et une PluginError explique pourquoi.
        """
        if not NAME_RE.fullmatch(plugin_name or ""):
            raise PluginError(f"nom de plugin invalide « {plugin_name} » (minuscules, chiffres et _)")
        file_name = file_name or f"{plugin_name}.py"
        if not re.fullmatch(r"[a-z][a-z0-9_]*\.py", file_name) or file_name.startswith("test_"):
            raise PluginError(f"nom de fichier invalide « {file_name} »")
        try:
            compile(source_code, f"{plugin_name}/{file_name}", "exec")
        except SyntaxError as exc:
            raise PluginError(f"le code ne compile pas (ligne {exc.lineno} : {exc.msg})") from exc
        folder = self.dir / plugin_name
        target = folder / file_name
        with self._lock:
            new_folder = not folder.exists()
            previous = target.read_text(encoding="utf-8") if target.exists() else None
            folder.mkdir(parents=True, exist_ok=True)
            target.write_text(source_code, encoding="utf-8")
            report = self.reload()
            if plugin_name in report["erreurs"]:
                error = report["erreurs"][plugin_name]
                if previous is None:                    # retour à l'état d'avant
                    target.unlink()
                    if new_folder and not any(folder.iterdir()):
                        folder.rmdir()
                else:
                    target.write_text(previous, encoding="utf-8")
                self.reload()
                self.errors.pop(plugin_name, None)
                self._failed.pop(plugin_name, None)
                raise PluginError(f"plugin « {plugin_name} » non chargé : {error}")
            return self.loaded[plugin_name]

    def functions(self, plugin_name: str) -> list[str]:
        with self._lock:
            record = self._record(plugin_name)
            return sorted({name for m in record.modules for name in _public_functions(m)})

    def execute(self, plugin_name: str, function_name: str, *args, **kwargs):
        """Appelle une fonction publique d'un plugin chargé (toujours la dernière version)."""
        with self._lock:
            record = self._record(plugin_name)
            func = next((_public_functions(m)[function_name] for m in reversed(record.modules)
                         if function_name in _public_functions(m)), None)
        if func is None:
            dispo = ", ".join(self.functions(plugin_name)) or "aucune"
            raise PluginError(f"pas de fonction « {function_name} » dans « {plugin_name} » "
                              f"(disponibles : {dispo})")
        return func(*args, **kwargs)      # appelée hors du verrou : un rechargement peut avoir lieu

    def _record(self, plugin_name: str) -> PluginRecord:
        record = self.loaded.get(plugin_name)
        if record is None:
            hint = f" (erreur : {self.errors[plugin_name]})" if plugin_name in self.errors else ""
            raise PluginError(f"plugin « {plugin_name} » non chargé{hint}")
        return record

    def tools(self) -> dict[str, Tool]:
        with self._lock:
            return {t.name: t for r in self.loaded.values() for t in r.tools}

    # --- Branchement au cerveau ----------------------------------------------------------------

    def attach(self, brain) -> None:
        """Le cerveau reçoit (et recevra à chaque changement) : outils du cœur + plugins."""
        core = {n: t for n, t in brain.tools.items() if n in self.core_names} or dict(brain.tools)
        if not self.core_names:
            self.core_names = frozenset(core)

        def update(plugin_tools: dict) -> None:
            brain.tools = {**plugin_tools, **core}     # remplacement atomique ; le cœur gagne

        self._listeners.append(update)
        update(self.tools())

    # --- Surveillance en arrière-plan ---------------------------------------------------------

    def start(self) -> "PluginManager":
        if self._thread is None:
            self._thread = threading.Thread(target=self._watch, daemon=True, name="jarvis-plugins")
            self._thread.start()
        return self

    def _watch(self) -> None:
        while not self._halt.is_set():
            try:
                self.reload()
            except Exception as exc:              # la surveillance ne doit jamais mourir
                log.warning("surveillance des plugins : %s", exc)
            self._halt.wait(self.interval_s)

    def stop(self) -> None:
        self._halt.set()
        if self._thread:
            self._thread.join(timeout=5)

    # --- Rapports -----------------------------------------------------------------------------

    @staticmethod
    def summary(report: dict) -> str:
        parts = []
        for key, label in (("charges", "chargé"), ("recharges", "rechargé"), ("decharges", "déchargé")):
            if report[key]:
                parts.append(f"{label} : {', '.join(report[key])}")
        for name, err in report["erreurs"].items():
            parts.append(f"erreur dans {name} : {err}")
        return " ; ".join(parts) or "rien n'a changé"

    def status_text(self) -> str:
        with self._lock:
            if not self.loaded and not self.errors:
                return "Aucune extension chargée."
            lines = []
            for name, r in sorted(self.loaded.items()):
                v = f" v{r.version}" if r.version else ""
                lines.append(f"- {name}{v} : {', '.join(t.name for t in r.tools)}")
            for name, err in sorted(self.errors.items()):
                lines.append(f"- ⚠️ {name} : {err}"
                             + (" (l'ancienne version reste active)" if name in self.loaded else ""))
            return "Extensions :\n" + "\n".join(lines)


# --- Couplage avec le générateur de code ------------------------------------------------------

def generate_and_load(config_path: str, manager: PluginManager, root: Path = JARVIS_ROOT) -> str:
    """Génère une capacité depuis une config YAML (scaffold) puis la charge à chaud."""
    from scaffold.core import Generator, Pack, ScaffoldError, load_config

    try:
        config = load_config(Path(config_path).expanduser())
        pack = Pack.load(config.pop("pack", None) or "jarvis-capacite")
        gen = Generator(pack, root)
        actions = gen.plan(config, update=True)   # régénère en gardant le code métier manuel
    except ScaffoldError as exc:
        return f"Je n'ai pas pu générer la capacité : {exc}"
    gen.apply(actions)
    written = [str(a.path.relative_to(gen.root)) for a in actions
               if a.kind in ("creer", "ecraser", "mettre_a_jour")]
    report = manager.reload()
    if report["erreurs"]:
        return "Code généré, mais le chargement a échoué : " + manager.summary(report)
    if not written:
        return "Rien à changer : la capacité est déjà à jour."
    return (f"Capacité générée ({len(written)} fichier(s)) et chargée à chaud, sans redémarrage : "
            f"{manager.summary(report)}. Complète la logique dans les zones « manuel ».")


def build_plugin_tools(manager: PluginManager) -> list[Tool]:
    s = {"type": "string"}

    def obj(props, req):
        return {"type": "object", "properties": props, "required": req}

    return [
        Tool(name="extensions_chargees",
             description="Liste les extensions (plugins) chargées et leurs éventuelles erreurs.",
             parameters=obj({}, []), run=manager.status_text),
        Tool(name="recharger_extensions",
             description="Recharge tout de suite les extensions modifiées (sans redémarrer Jarvis).",
             parameters=obj({}, []), run=lambda: PluginManager.summary(manager.reload())),
        Tool(name="generer_capacite",
             description=("Génère une nouvelle capacité à partir d'un fichier de configuration YAML "
                          "(générateur scaffold) et la charge à chaud, sans redémarrage."),
             parameters=obj({"config": {**s, "description": "Chemin du fichier YAML de la capacité."}},
                            ["config"]),
             run=lambda config: generate_and_load(config, manager),
             confirm=lambda config: (f"Je vais générer le code de la capacité décrite dans {config} "
                                     "et l'activer tout de suite. OK ?")),
    ]
