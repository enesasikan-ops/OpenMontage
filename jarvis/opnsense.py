"""Fil d'alarme sur le bastion OPNsense — l'intrus enfermé dans la cage de verre.

OPNsense segmente le réseau en VLAN : le CŒUR (serveur Jarvis) et l'IoT (caméras,
ampoules) sont aveugles l'un à l'autre. Si une ampoule piratée tente de scanner le
réseau pour trouver le serveur, OPNsense BLOQUE — et journalise. Jarvis lit ce journal
et t'alerte en silence : quelqu'un, depuis l'IoT, essaie d'atteindre le cœur.

OPNsense est un pare-feu (une appliance), pas un module Python : Jarvis ne le pilote
pas, il OBSERVE ses blocages via son API locale. La logique (quel blocage est une
tentative de franchissement IoT→cœur) est pure et testée ; la récupération est injectée.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
from typing import Callable

import config

log = logging.getLogger("jarvis.opnsense")

BLOCAGES = {"block", "drop", "reject"}


def dans_reseau(ip: str, cidrs) -> bool:
    try:
        adr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for c in cidrs:
        try:
            if adr in ipaddress.ip_network(c, strict=False):
                return True
        except ValueError:
            continue
    return False


def franchissements(evenements: list, coeur, iot) -> list:
    """Blocages dont la source est dans l'IoT et la destination dans le cœur."""
    out = []
    for ev in evenements or []:
        if str(ev.get("action", "")).lower() not in BLOCAGES:
            continue
        if dans_reseau(ev.get("src", ""), iot) and dans_reseau(ev.get("dst", ""), coeur):
            out.append(ev)
    return out


def _cle(ev: dict) -> str:
    return f"{ev.get('__timestamp__', '')}|{ev.get('src')}|{ev.get('dst')}|{ev.get('dstport', '')}"


def message(ev: dict) -> str:
    port = f":{ev.get('dstport')}" if ev.get("dstport") else ""
    return (f"🚨 Un appareil IoT ({ev.get('src')}) a tenté d'atteindre le cœur du réseau "
            f"({ev.get('dst')}{port}) — bloqué par OPNsense. Appareil peut-être compromis.")


def _fetch_api() -> list:
    """Récupère les derniers évènements du pare-feu via l'API OPNsense."""
    import base64
    import json
    import urllib.request

    auth = base64.b64encode(f"{config.OPNSENSE_KEY}:{config.OPNSENSE_SECRET}".encode()).decode()
    url = config.OPNSENSE_URL.rstrip("/") + "/api/diagnostics/firewall/log"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=10) as r:          # API locale configurée
        data = json.loads(r.read().decode("utf-8") or "[]")
    return data if isinstance(data, list) else data.get("rows", [])


class OpnsenseWatcher(threading.Thread):
    def __init__(self, fetch: Callable, notify: Callable[[str], None],
                 coeur, iot, interval_s: float = 60.0, evidence=None):
        super().__init__(daemon=True, name="jarvis-opnsense")
        self.fetch = fetch
        self.notify = notify
        self.coeur = coeur
        self.iot = iot
        self.interval_s = interval_s
        self.evidence = evidence
        self._halt = threading.Event()
        self._vus: "set | None" = None

    def un_tour(self) -> list:
        try:
            evenements = self.fetch()
        except Exception:
            log.warning("journal OPNsense indisponible")
            return []
        tentatives = franchissements(evenements, self.coeur, self.iot)
        if self._vus is None:                 # premier passage : on apprend sans alerter
            self._vus = {_cle(e) for e in tentatives}
            return []
        nouvelles = [e for e in tentatives if _cle(e) not in self._vus]
        self._vus = {_cle(e) for e in tentatives}
        for ev in nouvelles:
            if self.evidence is not None:
                try:
                    self.evidence.consigner(f"franchissement IoT→cœur : {ev.get('src')} -> {ev.get('dst')}")
                except Exception:
                    log.exception("journal de preuves OPNsense")
            try:
                self.notify(message(ev))
            except Exception:
                log.exception("alerte OPNsense")
        return nouvelles

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.un_tour()

    def arreter(self) -> None:
        self._halt.set()


def build_opnsense_tools(fetch: "Callable | None" = None) -> list:
    from tools import Tool

    if not (config.OPNSENSE and config.OPNSENSE_KEY):
        return []
    fetch = fetch or _fetch_api

    def point_pare_feu() -> str:
        try:
            tentatives = franchissements(fetch(), config.OPNSENSE_COEUR, config.OPNSENSE_IOT)
        except Exception:
            return "Je n'arrive pas à lire le journal du pare-feu OPNsense."
        if not tentatives:
            return "Pare-feu OPNsense : aucune tentative de franchissement IoT→cœur. La cage tient."
        srcs = ", ".join(sorted({e.get("src", "?") for e in tentatives}))
        return (f"⚠️ {len(tentatives)} tentative(s) de franchissement IoT→cœur bloquée(s). "
                f"Appareils concernés : {srcs}.")

    return [Tool(
        name="point_pare_feu",
        description=("Fait le point sur le pare-feu OPNsense : tentatives d'un appareil IoT "
                     "pour atteindre le cœur du réseau (signe d'un objet compromis). Lecture seule."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=point_pare_feu,
    )]


def make_opnsense_watcher(notify, evidence=None, fetch=None) -> "OpnsenseWatcher | None":
    if not (config.OPNSENSE and config.OPNSENSE_KEY):
        return None
    return OpnsenseWatcher(fetch or _fetch_api, notify, config.OPNSENSE_COEUR,
                           config.OPNSENSE_IOT, interval_s=config.OPNSENSE_INTERVALLE, evidence=evidence)
