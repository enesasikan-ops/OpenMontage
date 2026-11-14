"""Consignes de comportement — comment TU veux que Jarvis pense et réponde.

« Améliorer sa façon de penser » sans qu'il se réécrive tout seul : tu lui dictes des
consignes durables (« sois plus bref sur la sécurité », « propose toujours avant d'agir »,
« rappelle-moi les piles faibles »), il les range et les applique en les plaçant en tête de
ses instructions. Tu peux les relire et les effacer.

Lignes tenues :
- C'est TOI qui écris ces consignes (un seul utilisateur autorisé) ; Jarvis ne modifie pas
  sa pensée de sa propre initiative, et aucun optimiseur nocturne ne touche au prompt.
- Les garde-fous RÉELS (confirmation des actions sensibles, cœur protégé) sont dans le CODE,
  pas dans le prompt : une consigne ne peut pas les désactiver. Elles règlent le ton et le
  comportement, pas la sécurité.
"""

from __future__ import annotations

import json
from pathlib import Path


class Preferences:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.items: list = self._load()

    def _load(self) -> list:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        return [str(c) for c in data.get("consignes", [])]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"consignes": self.items}, ensure_ascii=False, indent=2),
                                 "utf-8")
        except OSError:
            pass

    def ajouter(self, consigne: str) -> str:
        c = (consigne or "").strip()
        if not c:
            return "Quelle consigne dois-je retenir ?"
        if c in self.items:
            return "C'est déjà une de mes consignes."
        self.items.append(c)
        self._save()
        return f"C'est noté, j'y veillerai : {c}"

    def retirer(self, mot: str) -> str:
        m = (mot or "").lower().strip()
        vises = [c for c in self.items if m and m in c.lower()]
        if not vises:
            return f"Aucune consigne ne correspond à « {mot} »."
        self.items = [c for c in self.items if c not in vises]
        self._save()
        return "J'abandonne : " + " ; ".join(vises)

    def as_text(self) -> str:
        return "\n".join(f"- {c}" for c in self.items)


def directives(prefs: "Preferences | None" = None) -> str:
    """Bloc à insérer dans les instructions du modèle (vide si aucune consigne)."""
    import config
    p = prefs or Preferences(config.PREFERENCES_FILE)
    if not p.items:
        return ""
    return "\nConsignes personnelles à respecter :\n" + p.as_text()


def build_preference_tools(prefs: "Preferences | None" = None) -> list:
    from tools import Tool

    import config
    prefs = prefs or Preferences(config.PREFERENCES_FILE)

    return [
        Tool(name="retenir_consigne",
             description=("Retient une consigne durable sur TA façon de te comporter ou de répondre "
                          "(« sois plus bref », « propose toujours avant d'agir »). À utiliser quand "
                          "l'utilisateur te corrige ou dit comment il te veut."),
             parameters={"type": "object",
                         "properties": {"consigne": {"type": "string", "description": "la consigne, en une phrase"}},
                         "required": ["consigne"]},
             run=lambda consigne: prefs.ajouter(consigne)),
        Tool(name="oublier_consigne",
             description="Abandonne une consigne de comportement qui contient un mot-clé.",
             parameters={"type": "object",
                         "properties": {"mot": {"type": "string", "description": "mot-clé de la consigne"}},
                         "required": ["mot"]},
             run=lambda mot: prefs.retirer(mot)),
        Tool(name="mes_consignes",
             description="Liste les consignes de comportement que Jarvis respecte actuellement.",
             parameters={"type": "object", "properties": {}, "required": []},
             run=lambda: ("Mes consignes :\n" + prefs.as_text()) if prefs.items
             else "Je n'ai pas de consigne particulière pour l'instant."),
    ]
