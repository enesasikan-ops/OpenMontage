"""Intégrité du cœur : Jarvis surveille son PROPRE code.

Un « tripwire » : on garde l'empreinte (SHA-256) de chaque fichier du cœur. Si l'un
d'eux change, disparaît ou réapparaît sans passer par le circuit validé (ta ✅ ou une
proposition de cœur relue), Jarvis le signale. C'est la détection d'une altération de
ses propres garde-fous.

Référence persistée (survit aux redémarrages) : un changement fait pendant que Jarvis
était éteint est donc aussi détecté. Après un changement légitime, le propriétaire
« rebase » pour accepter le nouvel état.

Limite : un attaquant capable de modifier les fichiers peut aussi modifier le fichier de
référence. C'est un signal précoce, pas une protection inviolable ; à compléter par des
droits de fichiers stricts et un compte dédié.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from growth import PROTECTED
from skills import JsonStore

RACINE = Path(__file__).resolve().parent

# Le cœur = les fichiers protégés (sauf .env, qui change légitimement et contient des
# secrets) + les modules de sécurité eux-mêmes.
_SECURITE = ("plugin_manager.py", "growth.py", "core_proposals.py", "netguard.py", "core_integrity.py")
CORE_FILES = tuple(sorted((set(PROTECTED) - {".env"}) | set(_SECURITE)))


def _empreinte(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CoreIntegrity:
    def __init__(self, path: Path, racine: Path = RACINE, fichiers=CORE_FILES):
        self.racine = Path(racine)
        self.fichiers = tuple(fichiers)
        self.store = JsonStore(path, {})
        if not self.store.data:                 # premier passage : on mémorise, pas d'alerte
            self.store.data = self._etat()
            self.store.save()

    def _etat(self) -> "dict[str, str | None]":
        etat: "dict[str, str | None]" = {}
        for f in self.fichiers:
            p = self.racine / f
            etat[f] = _empreinte(p) if p.is_file() else None
        return etat

    def verifier(self) -> "list[tuple[bool, str]]":
        """[(critique ?, message)] — fichier du cœur modifié / supprimé / réapparu."""
        actuel = self._etat()
        reference = self.store.data
        alertes: "list[tuple[bool, str]]" = []
        for f in self.fichiers:
            avant, maintenant = reference.get(f), actuel.get(f)
            if avant == maintenant:
                continue
            if maintenant is None:
                alertes.append((True, f"fichier du cœur SUPPRIMÉ : {f}"))
            elif avant is None:
                alertes.append((True, f"fichier du cœur réapparu : {f}"))
            else:
                alertes.append((True, f"fichier du cœur MODIFIÉ hors circuit : {f}"))
        return alertes

    def rebaser(self) -> str:
        """Accepte l'état actuel comme nouvelle référence (après un changement validé)."""
        self.store.data = self._etat()
        self.store.save()
        return "Référence du cœur mise à jour : l'état actuel est désormais la base."
