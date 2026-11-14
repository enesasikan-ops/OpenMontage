"""Surveillance de la liaison Starlink (l'Internet de la maison).

Starlink, c'est le WAN, pas le Wi-Fi : on ne parle pas de sécurité d'accès mais de
RÉSILIENCE. L'antenne expose une API locale (gRPC sur 192.168.100.1) ; Jarvis la lit et
t'alerte sur une coupure, une obstruction (arbres, neige) ou une alerte matériel.

Pourquoi ça compte : si l'uplink tombe, le renfort (Claude/Gemini), Telegram/Signal et
l'accès à distance tombent avec. Jarvis le voit et te prévient — localement, en lisant
l'antenne, sans rien envoyer dehors.

La lecture gRPC nécessite `starlink-grpc-tools` (pip install starlink-grpc-tools). La
logique d'analyse, elle, est indépendante et testée avec des données injectées.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import config

log = logging.getLogger("jarvis.starlink")

SEUIL_OBSTRUCTION = 0.01     # 1 % : au-delà, on signale
SEUIL_LATENCE_MS = 150


def etat(getter: Callable) -> dict:
    """Appelle le getter et normalise avec des valeurs par défaut sûres."""
    brut = getter() or {}
    return {
        "state": brut.get("state", "CONNECTED"),
        "latence_ms": brut.get("latence_ms", brut.get("pop_ping_latency_ms", 0)) or 0,
        "obstruction": brut.get("obstruction", brut.get("fraction_obstructed", 0.0)) or 0.0,
        "alertes": list(brut.get("alertes", []) or []),
        "uptime_s": brut.get("uptime_s", 0) or 0,
    }


def analyser(e: dict) -> dict:
    """Renvoie {probleme: bool, messages: [...]} à partir d'un état normalisé."""
    messages = []
    if e.get("state") != "CONNECTED":
        messages.append(f"Connexion Starlink interrompue (état : {e.get('state')}).")
    obstruction = e.get("obstruction", 0.0)
    if obstruction > SEUIL_OBSTRUCTION:
        messages.append(f"Antenne obstruée à {obstruction * 100:.0f} % (arbres, neige ?).")
    for alerte in e.get("alertes", []):
        messages.append(f"Alerte antenne : {alerte}.")
    if e.get("latence_ms", 0) and e["latence_ms"] > SEUIL_LATENCE_MS and e.get("state") == "CONNECTED":
        messages.append(f"Latence élevée ({e['latence_ms']:.0f} ms).")
    return {"probleme": bool(messages), "messages": messages}


def rapport(e: dict) -> str:
    a = analyser(e)
    if not a["probleme"]:
        return (f"Starlink : connecté, {e.get('latence_ms', 0):.0f} ms de latence, "
                f"{e.get('obstruction', 0.0) * 100:.0f} % d'obstruction. Tout va bien.")
    return "🛰️ Starlink — " + " ".join(a["messages"])


def _status_grpc() -> dict:
    """Lit l'antenne Starlink en local (via starlink-grpc-tools)."""
    import starlink_grpc

    general, obstruction, alertes = starlink_grpc.status_data()
    actives = [nom for nom, vrai in (alertes or {}).items() if vrai]
    return {
        "state": general.get("state", "CONNECTED"),
        "latence_ms": general.get("pop_ping_latency_ms", 0),
        "obstruction": obstruction.get("fraction_obstructed", 0.0),
        "alertes": actives,
        "uptime_s": general.get("uptime", 0),
    }


class StarlinkWatcher(threading.Thread):
    def __init__(self, getter: Callable, notify: Callable[[str], None], interval_s: float = 60.0):
        super().__init__(daemon=True, name="jarvis-starlink")
        self.getter = getter
        self.notify = notify
        self.interval_s = interval_s
        self._halt = threading.Event()
        self._vus: set = set()
        self._avait_probleme = False

    def un_tour(self) -> list:
        try:
            a = analyser(etat(self.getter))
        except Exception:
            log.warning("Starlink injoignable")
            return []
        nouveaux = [m for m in a["messages"] if m not in self._vus]
        for m in nouveaux:
            try:
                self.notify("🛰️ " + m)
            except Exception:
                log.exception("alerte Starlink")
        if not a["messages"] and self._avait_probleme:
            self.notify("🛰️ Connexion Starlink rétablie.")
        self._vus = set(a["messages"])
        self._avait_probleme = a["probleme"]
        return nouveaux

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.un_tour()

    def arreter(self) -> None:
        self._halt.set()


def build_starlink_tools(getter: "Callable | None" = None) -> list:
    from tools import Tool

    if not config.STARLINK:
        return []
    getter = getter or _status_grpc

    def etat_internet() -> str:
        try:
            return rapport(etat(getter))
        except Exception:
            return ("Je n'arrive pas à lire l'antenne Starlink (starlink-grpc-tools installé ? "
                    "l'antenne est-elle joignable sur 192.168.100.1 ?).")

    return [Tool(
        name="etat_internet",
        description=("Donne l'état de la liaison Internet Starlink : connecté, latence, "
                     "obstruction, alertes. « comment va l'Internet ? », « Starlink va bien ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=etat_internet,
    )]


def make_starlink_watcher(notify, getter: "Callable | None" = None) -> "StarlinkWatcher | None":
    if not config.STARLINK:
        return None
    return StarlinkWatcher(getter or _status_grpc, notify, interval_s=config.STARLINK_INTERVALLE)
