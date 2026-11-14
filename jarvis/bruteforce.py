"""Corrélation anti-force-brute — relier des échecs isolés en une campagne.

Un échec d'authentification isolé n'est rien. DIX échecs de la même source en une minute,
c'est une attaque par force brute. Ce module AGRÈGE les signaux d'échec (honeypot,
labyrinthe, rejets d'auth…) par source et, au-delà d'un seuil dans une fenêtre de temps,
lève UNE alerte corrélée et PROPOSE un blocage.

Ligne tenue : on PROPOSE (« dis bloque <ip> »), on ne bloque pas en aveugle — une IP source
peut être usurpée, et le blocage reste une décision du propriétaire (ipblock.py). Aucune
contre-attaque : on ne touche jamais la machine distante.
"""

from __future__ import annotations

import ipaddress
import logging
import time
from collections import deque
from typing import Callable

log = logging.getLogger("jarvis.bruteforce")

SEUIL = 8          # échecs d'une même source…
FENETRE_S = 60.0   # …dans cette fenêtre → campagne de force brute
COOLDOWN_S = 300.0  # on ne ré-alerte pas sur la même source avant ce délai


def _est_ip(source: str) -> bool:
    try:
        ipaddress.ip_address(source)
        return True
    except ValueError:
        return False


class BruteForceDetector:
    def __init__(self, notify: "Callable[[str], None] | None" = None,
                 seuil: int = SEUIL, fenetre_s: float = FENETRE_S, cooldown_s: float = COOLDOWN_S,
                 horloge: Callable[[], float] = time.monotonic):
        self.notify = notify
        self.seuil = seuil
        self.fenetre_s = fenetre_s
        self.cooldown_s = cooldown_s
        self.horloge = horloge
        self._echecs: dict = {}            # source -> deque[timestamps]
        self._cooldown: dict = {}          # source -> timestamp jusqu'auquel on se tait

    def _recents(self, source: str, maintenant: float) -> deque:
        dq = self._echecs.setdefault(source, deque())
        while dq and maintenant - dq[0] > self.fenetre_s:
            dq.popleft()
        return dq

    def enregistrer(self, source: str, detail: str = "") -> "str | None":
        """Enregistre un échec. Renvoie (et notifie) le message d'alerte si le seuil est franchi."""
        source = (source or "").strip()
        if not source:
            return None
        maintenant = self.horloge()
        dq = self._recents(source, maintenant)
        dq.append(maintenant)
        if len(dq) < self.seuil or maintenant < self._cooldown.get(source, 0.0):
            return None
        self._cooldown[source] = maintenant + self.cooldown_s
        message = (f"Force brute détectée : {len(dq)} échecs de {source} "
                   f"en moins de {int(self.fenetre_s)} s")
        if detail:
            message += f" ({detail})"
        message += "."
        if _est_ip(source):
            message += f" Dis « bloque {source} » pour lui fermer la porte."
        if self.notify is not None:
            try:
                self.notify("🚨 " + message)
            except Exception:
                log.exception("notification force brute")
        return message

    def actifs(self, minimum: int = 3) -> list:
        """Sources ayant au moins `minimum` échecs récents (pour un point de situation)."""
        maintenant = self.horloge()
        out = [(len(self._recents(s, maintenant)), s) for s in list(self._echecs)]
        return sorted(((n, s) for n, s in out if n >= minimum), reverse=True)

    def rapport(self) -> str:
        actifs = self.actifs()
        if not actifs:
            return "Aucune tentative de force brute en cours."
        lignes = [f"- {s} : {n} échecs récents" for n, s in actifs]
        return "⚠️ Sources suspectes (échecs répétés) :\n" + "\n".join(lignes)


_DET: "BruteForceDetector | None" = None


def detecteur(notify: "Callable[[str], None] | None" = None) -> BruteForceDetector:
    """Singleton partagé entre les capteurs (honeypot, labyrinthe) et l'outil de situation."""
    global _DET
    if _DET is None:
        _DET = BruteForceDetector(notify)
    elif notify is not None and _DET.notify is None:
        _DET.notify = notify
    return _DET


def build_bruteforce_tools() -> list:
    from tools import Tool

    det = detecteur()
    return [Tool(
        name="point_force_brute",
        description=("Fait le point sur les tentatives de FORCE BRUTE en cours (sources qui "
                     "multiplient les échecs d'authentification). « qui essaie de forcer l'entrée ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=lambda: det.rapport(),
    )]
