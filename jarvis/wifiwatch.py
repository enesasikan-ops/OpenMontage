"""Détection d'instabilité Wi-Fi — le symptôme d'une attaque de déauthentification.

Le PMF (802.11w) EMPÊCHE la déauth falsifiée ; Jarvis, lui, DÉTECTE le symptôme : un
appareil qui se déconnecte en rafale, ou plusieurs qui tombent d'un coup. Il lit la
liste des appareils connectés (via la Freebox) à intervalle régulier et alerte.

Honnêteté : une instabilité peut venir d'une attaque de déauth, MAIS aussi d'un signal
faible ou d'un appareil défaillant. Jarvis signale le fait (« X s'est déconnecté 5 fois
en 2 min »), il ne conclut pas à votre place. La protection, elle, reste le PMF sur l'AP.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import config

log = logging.getLogger("jarvis.wifi")

MASSE = 3   # nombre d'appareils tombant d'un coup qui évoque une déauth de masse


class StabilityTracker:
    def __init__(self, seuil: int = 4, fenetre_s: float = 120.0,
                 horloge: "Callable[[], float]" = time.monotonic):
        self.seuil = seuil
        self.fenetre_s = fenetre_s
        self.horloge = horloge
        self._precedent: "set | None" = None
        self._chutes: dict = {}          # appareil -> [horodatages de déconnexion]

    def observer(self, actifs: set) -> list:
        """Reçoit l'ensemble des appareils ACTIFS. Renvoie les alertes nouvelles."""
        maintenant = self.horloge()
        actifs = set(actifs)
        alertes = []
        if self._precedent is None:      # premier passage : on apprend sans alerter
            self._precedent = actifs
            return []

        partis = self._precedent - actifs
        self._precedent = actifs

        if len(partis) >= MASSE:         # plusieurs d'un coup : signature de déauth de masse
            alertes.append(f"⚠️ {len(partis)} appareils déconnectés d'un coup "
                           "— possible attaque de déauthentification. Le PMF (802.11w) protège-t-il l'AP ?")

        for appareil in partis:
            self._chutes.setdefault(appareil, []).append(maintenant)

        for appareil, temps in list(self._chutes.items()):
            recents = [t for t in temps if maintenant - t <= self.fenetre_s]
            if len(recents) >= self.seuil:
                alertes.append(f"⚠️ « {appareil} » s'est déconnecté {len(recents)} fois en peu de temps "
                               "(déauth, signal faible ou appareil défaillant ?).")
                self._chutes[appareil] = []      # réarme après alerte
            elif recents:
                self._chutes[appareil] = recents
            else:
                self._chutes.pop(appareil, None)
        return alertes


class WifiStabilityWatcher(threading.Thread):
    def __init__(self, client, notify: Callable[[str], None], tracker: StabilityTracker,
                 interval_s: float = 20.0):
        super().__init__(daemon=True, name="jarvis-wifi-stabilite")
        self.client = client
        self.notify = notify
        self.tracker = tracker
        self.interval_s = interval_s
        self._halt = threading.Event()

    def un_tour(self) -> list:
        try:
            appareils = self.client.appareils()
        except Exception:
            log.warning("liste des appareils Wi-Fi indisponible")
            return []
        actifs = {a["nom"] or a["mac"] for a in appareils if a.get("actif")}
        alertes = self.tracker.observer(actifs)
        for a in alertes:
            try:
                self.notify(a)
            except Exception:
                log.exception("alerte stabilité Wi-Fi")
        return alertes

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.un_tour()

    def arreter(self) -> None:
        self._halt.set()


def make_wifi_watcher(notify) -> "WifiStabilityWatcher | None":
    if not (config.WIFI_STABILITE and config.FREEBOX_TOKEN):
        return None
    from freebox import FreeboxClient

    client = FreeboxClient(config.FREEBOX_URL, config.FREEBOX_TOKEN)
    tracker = StabilityTracker(seuil=config.WIFI_STABILITE_SEUIL,
                               fenetre_s=config.WIFI_STABILITE_FENETRE)
    return WifiStabilityWatcher(client, notify, tracker, interval_s=config.WIFI_STABILITE_INTERVALLE)
