"""Défense active (sur la machine de Jarvis, jamais offensive).

Deux briques proactives :
- EvidenceLog : journal horodaté des alertes de sécurité (trace pour comprendre après coup).
- CoreBackup  : copie saine des fichiers du cœur ; si on les trafique, Jarvis peut les
  RESTAURER à l'état connu (réversible, et seulement sur confirmation du propriétaire).

Principe : détecter → garder la preuve → PROPOSER une riposte défensive → le propriétaire
confirme → agir. Rien de destructeur n'est fait tout seul, et jamais rien d'offensif.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from core_integrity import CORE_FILES, RACINE
from skills import JsonStore


class EvidenceLog:
    """Journal horodaté des alertes. Append-only, pour l'analyse après coup."""

    def __init__(self, path: Path, horloge=None):
        self.store = JsonStore(path, {"journal": []})
        self.store.data.setdefault("journal", [])
        self._horloge = horloge or (lambda: datetime.now(ZoneInfo(config.TIMEZONE)))

    def consigner(self, message: str) -> str:
        quand = self._horloge().isoformat(timespec="seconds")
        self.store.data["journal"].append({"quand": quand, "quoi": message})
        self.store.save()
        return quand

    def recent(self, n: int = 10) -> list:
        return self.store.data["journal"][-n:]


class CoreBackup:
    """Copie de référence des fichiers du cœur, pour pouvoir les restaurer si trafiqués."""

    def __init__(self, dossier: Path, racine: Path = RACINE, fichiers=CORE_FILES):
        self.dossier = Path(dossier)
        self.racine = Path(racine)
        self.fichiers = tuple(fichiers)

    def sauvegarder(self) -> int:
        """Prend un instantané de l'état ACTUEL comme référence saine. Renvoie le nb de fichiers."""
        self.dossier.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in self.fichiers:
            src = self.racine / f
            if src.is_file():
                (self.dossier / f).write_bytes(src.read_bytes())
                n += 1
        return n

    def peut_restaurer(self, fichier: str) -> bool:
        return fichier in self.fichiers and (self.dossier / fichier).is_file()

    def restaurer(self, fichier: str) -> str:
        """Remet la version saine par-dessus la version trafiquée. À confirmer par le propriétaire."""
        if fichier not in self.fichiers:
            raise ValueError(f"« {fichier} » n'est pas un fichier du cœur.")
        source = self.dossier / fichier
        if not source.is_file():
            raise ValueError(f"pas de sauvegarde pour {fichier} (fais « sauvegarde cœur » après une install saine).")
        (self.racine / fichier).write_bytes(source.read_bytes())
        return f"{fichier} restauré depuis la sauvegarde de référence. Redémarre Jarvis."
