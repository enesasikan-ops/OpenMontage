"""Surveillance de cybersécurité en continu.

Un fil qui, à intervalle régulier, interroge :
- la sentinelle machine (ports ouverts, appareils réseau, pare-feu, comptes admin…) ;
- l'intégrité du cœur (le code de Jarvis a-t-il été modifié ?).
Chaque nouveauté est signalée une seule fois au propriétaire (via `notify`).
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable

log = logging.getLogger(__name__)

INTERVALLE_S = 300  # 5 min par défaut
_RE_FICHIER_MODIFIE = re.compile(r"fichier du cœur MODIFIÉ.*?:\s*(\S+)")


class SecurityWatcher(threading.Thread):
    def __init__(self, notify: Callable[[str], None], sentinel=None, integrity=None,
                 interval_s: float = INTERVALLE_S, quiet: "Callable[[], bool] | None" = None,
                 evidence=None, backup=None, auto_restore: bool = False):
        super().__init__(daemon=True, name="jarvis-cyberwatch")
        self.notify = notify
        self.sentinel = sentinel
        self.integrity = integrity
        self.interval_s = interval_s
        self.quiet = quiet
        self.evidence = evidence          # EvidenceLog : garde une trace des alertes critiques
        self.backup = backup              # CoreBackup : pour restaurer un fichier trafiqué
        self.auto_restore = auto_restore  # True = Jarvis répare tout seul (réversible)
        self._halt = threading.Event()
        self._vus: set[str] = set()

    def un_tour(self) -> "list[tuple[bool, str]]":
        """Un cycle de vérification. Renvoie les alertes NOUVELLES (déjà notifiées)."""
        evenements: "list[tuple[bool, str]]" = []
        if self.integrity is not None:            # priorité : le cœur de Jarvis
            try:
                evenements += self.integrity.verifier()
            except Exception:
                log.exception("vérification d'intégrité du cœur")
        if self.sentinel is not None:
            try:
                evenements += list(self.sentinel.check())
            except Exception:
                log.exception("vérification de la sentinelle")

        nouvelles = []
        for critique, message in evenements:
            if message in self._vus:
                continue
            self._vus.add(message)
            nouvelles.append((critique, message))

        for critique, message in nouvelles:
            if critique and self.evidence is not None:    # garder la preuve des alertes critiques
                try:
                    self.evidence.consigner(message)
                except Exception:
                    log.exception("journal de preuves")
            prefixe = "🚨 ALERTE SÉCURITÉ" if critique else "🛡️"
            try:
                self.notify(f"{prefixe} {message}")
            except Exception:
                log.exception("notification de sécurité")
            if critique:
                self._reparer(message)
        return nouvelles

    def _reparer(self, message: str) -> None:
        """Réaction automatique (si activée) : restaure un fichier du cœur trafiqué.

        Sûr et réversible : on remet une version SAINE connue, on ne génère pas de code.
        La génération d'un correctif, elle, reste gated derrière la ✅ du propriétaire.
        """
        if not self.auto_restore or self.backup is None:
            return
        m = _RE_FICHIER_MODIFIE.search(message)
        if not m:
            return
        fichier = m.group(1)
        if not self.backup.peut_restaurer(fichier):
            return
        try:
            resultat = self.backup.restaurer(fichier)
        except Exception:
            log.exception("auto-restauration")
            return
        avis = f"🛡️ Réaction automatique : {resultat}"
        if self.evidence is not None:
            try:
                self.evidence.consigner(f"auto-restauration : {fichier}")
            except Exception:
                log.exception("journal de preuves")
        try:
            self.notify(avis)
        except Exception:
            log.exception("notification de sécurité")

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            if self.quiet is not None and self.quiet():
                continue
            self.un_tour()

    def stop(self) -> None:
        self._halt.set()
