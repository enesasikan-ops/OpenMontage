"""Surveillance de cybersécurité en continu.

Un fil qui, à intervalle régulier, interroge :
- la sentinelle machine (ports ouverts, appareils réseau, pare-feu, comptes admin…) ;
- l'intégrité du cœur (le code de Jarvis a-t-il été modifié ?).
Chaque nouveauté est signalée une seule fois au propriétaire (via `notify`).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger(__name__)

INTERVALLE_S = 300  # 5 min par défaut


class SecurityWatcher(threading.Thread):
    def __init__(self, notify: Callable[[str], None], sentinel=None, integrity=None,
                 interval_s: float = INTERVALLE_S, quiet: "Callable[[], bool] | None" = None,
                 evidence=None):
        super().__init__(daemon=True, name="jarvis-cyberwatch")
        self.notify = notify
        self.sentinel = sentinel
        self.integrity = integrity
        self.interval_s = interval_s
        self.quiet = quiet
        self.evidence = evidence          # EvidenceLog : garde une trace des alertes critiques
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
        return nouvelles

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            if self.quiet is not None and self.quiet():
                continue
            self.un_tour()

    def stop(self) -> None:
        self._halt.set()
