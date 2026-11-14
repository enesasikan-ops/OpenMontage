"""Moteur du générateur de code (scaffolding).

Le moteur ne connaît AUCUNE architecture : tout ce qui est spécifique vit dans un
« pack de modèles » (scaffold/packs/<nom>/), qui déclare :
  - le schéma de configuration attendu (validé avant toute écriture),
  - la liste des fichiers à produire, avec leur chemin de sortie et une condition.

Pipeline :  charger la config → valider → construire le contexte → rendre les modèles
            → planifier (créer / ignorer / écraser / mettre à jour) → écrire (ou simuler).

Les 20 % de code écrits à la main vivent dans des ZONES MANUELLES :
    # >>> manuel: <id>
    ... ton code ...
    # <<< manuel: <id>
Lors d'une régénération en mode --update, ces zones sont conservées telles quelles.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

PACKS_DIR = Path(__file__).parent / "packs"

# Marqueurs en commentaire Python/YAML/shell (#) ou HTML/Markdown (<!-- ... -->).
ZONE_RE = re.compile(
    r"^[ \t]*(?:#|<!--) >>> manuel: (?P<id>[\w.-]+)[ \t]*(?:-->)?[ \t]*\n"
    r"(?P<body>.*?)"
    r"^[ \t]*(?:#|<!--) <<< manuel: (?P=id)[ \t]*(?:-->)?[ \t]*$",
    re.MULTILINE | re.DOTALL)

TYPES = {"str": str, "int": int, "bool": bool, "list": list, "dict": dict, "float": (int, float)}


class ScaffoldError(Exception):
    """Erreur lisible pour l'utilisateur (config invalide, pack introuvable...)."""


# --- Transformations de noms (disponibles comme filtres Jinja) ------------------------

def _words(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return [w for w in re.split(r"[^A-Za-z0-9]+", text) if w]


def snake(text: str) -> str:
    return "_".join(w.lower() for w in _words(text))


def kebab(text: str) -> str:
    return "-".join(w.lower() for w in _words(text))


def pascal(text: str) -> str:
    return "".join(w[:1].upper() + w[1:].lower() for w in _words(text))


def camel(text: str) -> str:
    p = pascal(text)
    return p[:1].lower() + p[1:]


def pyrepr(value) -> str:
    """Littéral Python sûr (chaînes échappées) pour insérer une valeur dans du code."""
    return repr(value)


# --- Pack de modèles -------------------------------------------------------------------

@dataclass
class Pack:
    name: str
    root: Path
    description: str
    schema: dict
    files: list[dict]
    notes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, name: str, packs_dir: Path = PACKS_DIR) -> "Pack":
        root = packs_dir / name
        manifest = root / "pack.yaml"
        if not manifest.exists():
            dispo = ", ".join(list_packs(packs_dir)) or "aucun"
            raise ScaffoldError(f"Pack « {name} » introuvable. Packs disponibles : {dispo}.")
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        return cls(name=name, root=root, description=data.get("description", ""),
                   schema=data.get("schema", {}), files=data.get("fichiers", []),
                   notes=data.get("notes", []))


def list_packs(packs_dir: Path = PACKS_DIR) -> list[str]:
    if not packs_dir.exists():
        return []
    return sorted(p.name for p in packs_dir.iterdir() if (p / "pack.yaml").exists())


# --- Validation déclarative ----------------------------------------------------------------

def validate(config: dict, schema: dict, path: str = "") -> tuple[dict, list[str]]:
    """Valide `config` selon `schema` et applique les valeurs par défaut.
    Renvoie (config complétée, liste de TOUTES les erreurs) — on signale tout d'un coup."""
    errors: list[str] = []
    if not isinstance(config, dict):
        return {}, [f"{path or 'la configuration'} doit être un objet (clé: valeur)."]
    out = dict(config)
    for key, rule in schema.items():
        where = f"{path}.{key}" if path else key
        if key not in out or out[key] is None:
            if rule.get("requis"):
                errors.append(f"« {where} » est obligatoire.")
                continue
            if "defaut" in rule:
                out[key] = rule["defaut"]
            continue
        value = out[key]
        expected = TYPES.get(rule.get("type", "str"), str)
        if isinstance(value, bool) and rule.get("type") in ("int", "float"):
            errors.append(f"« {where} » doit être un nombre.")
            continue
        if not isinstance(value, expected):
            errors.append(f"« {where} » doit être de type {rule.get('type', 'str')}.")
            continue
        if "motif" in rule and isinstance(value, str) and not re.fullmatch(rule["motif"], value):
            errors.append(f"« {where} » = « {value} » ne respecte pas le format attendu "
                          f"({rule.get('aide', rule['motif'])}).")
        if "choix" in rule and value not in rule["choix"]:
            errors.append(f"« {where} » doit valoir l'un de : {', '.join(map(str, rule['choix']))}.")
        if rule.get("type") == "list":
            if rule.get("non_vide") and not value:
                errors.append(f"« {where} » ne doit pas être vide.")
            if "elements" in rule:
                items = []
                for i, item in enumerate(value):
                    fixed, errs = validate(item, rule["elements"], f"{where}[{i}]")
                    items.append(fixed)
                    errors += errs
                out[key] = items
                if rule.get("unique"):
                    seen = [it.get(rule["unique"]) for it in items if isinstance(it, dict)]
                    dups = sorted({x for x in seen if seen.count(x) > 1})
                    if dups:
                        errors.append(f"« {where} » : doublons de « {rule['unique']} » : {', '.join(dups)}.")
    unknown = sorted(set(out) - set(schema))
    if unknown and schema:
        errors.append(f"Clé(s) inconnue(s) dans {path or 'la configuration'} : {', '.join(unknown)}.")
    return out, errors


# --- Zones manuelles ---------------------------------------------------------------------

def manual_zones(text: str) -> dict[str, str]:
    return {m.group("id"): m.group("body") for m in ZONE_RE.finditer(text)}


def merge_manual(new_text: str, old_text: str) -> tuple[str, list[str]]:
    """Réinjecte dans le nouveau rendu le contenu des zones manuelles de l'ancien fichier.
    Renvoie (texte fusionné, zones perdues : présentes avant, absentes du nouveau modèle)."""
    old = manual_zones(old_text)

    def keep(m: re.Match) -> str:
        zid = m.group("id")
        if zid not in old:
            return m.group(0)
        start = m.group(0).split("\n", 1)[0]
        end = m.group(0).rsplit("\n", 1)[-1]
        return f"{start}\n{old[zid]}{end}"

    merged = ZONE_RE.sub(keep, new_text)
    lost = sorted(set(old) - set(manual_zones(new_text)))
    return merged, lost


# --- Plan et écriture ------------------------------------------------------------------------

@dataclass
class Action:
    path: Path
    kind: str          # creer | ignorer | ecraser | mettre_a_jour | identique
    content: str
    diff: str = ""
    warnings: list[str] = field(default_factory=list)


class Generator:
    def __init__(self, pack: Pack, output_root: Path):
        self.pack = pack
        self.root = Path(output_root).resolve()
        self.env = Environment(loader=FileSystemLoader(str(pack.root)), undefined=StrictUndefined,
                               keep_trailing_newline=True, trim_blocks=True, lstrip_blocks=True)
        for f in (snake, kebab, pascal, camel, pyrepr):
            self.env.filters[f.__name__] = f

    def context(self, config: dict) -> dict:
        nom = config.get("nom", "")
        return {**config, "noms": {"snake": snake(nom), "kebab": kebab(nom),
                                   "pascal": pascal(nom), "camel": camel(nom)}}

    def _target(self, template: str, ctx: dict) -> Path:
        rel = self.env.from_string(template).render(ctx).strip()
        target = (self.root / rel).resolve()
        if self.root not in target.parents and target != self.root:
            raise ScaffoldError(f"Chemin de sortie refusé (hors du dossier cible) : {rel}")
        return target

    def plan(self, config: dict, force: bool = False, update: bool = False) -> list[Action]:
        config, errors = validate(config, self.pack.schema)
        if errors:
            raise ScaffoldError("Configuration invalide :\n- " + "\n- ".join(errors))
        ctx = self.context(config)
        actions = []
        for spec in self.pack.files:
            cond = spec.get("si")
            if cond and self.env.from_string("{{ " + cond + " }}").render(ctx).strip() not in ("True", "true", "1"):
                continue
            target = self._target(spec["sortie"], ctx)
            content = self.env.get_template(spec["modele"]).render(ctx)
            if not target.exists():
                actions.append(Action(target, "creer", content))
                continue
            old = target.read_text(encoding="utf-8")
            if update:
                content, lost = merge_manual(content, old)
                warns = [f"zone manuelle « {z} » absente du nouveau modèle : son code est à reprendre"
                         for z in lost]
            else:
                warns = []
            if content == old:
                actions.append(Action(target, "identique", content))
            elif update or force:
                diff = "".join(difflib.unified_diff(old.splitlines(True), content.splitlines(True),
                                                    str(target), str(target)))
                actions.append(Action(target, "mettre_a_jour" if update else "ecraser", content, diff, warns))
            else:
                actions.append(Action(target, "ignorer", content,
                                      warnings=["existe déjà (utilise --update ou --force)"]))
        return actions

    @staticmethod
    def apply(actions: list[Action]) -> None:
        for a in actions:
            if a.kind in ("creer", "ecraser", "mettre_a_jour"):
                a.path.parent.mkdir(parents=True, exist_ok=True)
                a.path.write_text(a.content, encoding="utf-8")


def load_config(path: Path) -> dict:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ScaffoldError(f"Fichier de configuration introuvable : {path}") from None
    except yaml.YAMLError as exc:
        raise ScaffoldError(f"Le fichier {path} n'est pas du YAML valide : {exc}") from None
    if not isinstance(data, dict):
        raise ScaffoldError(f"{path} doit contenir un objet YAML (clé: valeur).")
    return data
