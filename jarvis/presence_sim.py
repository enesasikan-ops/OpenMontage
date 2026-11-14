"""Simulation de présence « organique » — tromper l'observateur patient, en sécurité.

Allumer le salon à 20h00 pile tous les soirs ne trompe pas un cambrioleur qui observe
depuis plusieurs jours. Ce module rejoue TON comportement avec de la variation : des zones
(lumières, volets, prises) actives selon le moment de la journée, mais avec un aléa qui
casse la régularité mécanique. Idéalement nourri par tes vraies habitudes (habits.py).

GARDE-FOUS (non négociables) :
- JAMAIS d'action dangereuse pour « faire semblant » : on ne simule la présence qu'avec des
  lumières / prises / volets / media. Les SERRURES et le PORTAIL sont exclus par construction
  (on ne déverrouille pas une maison vide).
- Opt-in : tu armes le mode vacances ; sans ça, rien ne bouge.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Callable

import config
from habits import moment      # réutilise le découpage matin/après-midi/soir/nuit

log = logging.getLogger("jarvis.presence_sim")

# Domaines autorisés pour simuler une présence. 'lock'/serrure/portail en sont EXCLUS.
_SERVICES = {
    "light": ("turn_on", "turn_off"),
    "switch": ("turn_on", "turn_off"),
    "media_player": ("turn_on", "turn_off"),
    "cover": ("open_cover", "close_cover"),
}
_SAUT = 0.12   # probabilité de « sauter » une zone à ce tour (variation organique)


def zones_config() -> list:
    out = []
    for nom, d in (config.SIM_ZONES or {}).items():
        if not isinstance(d, dict) or not d.get("entite"):
            continue
        ent = d["entite"]
        dom = (d.get("domaine") or ent.split(".")[0]).lower()
        if dom not in _SERVICES or ent.startswith("lock."):
            continue      # jamais de serrure/portail dans une simulation de présence
        out.append({"nom": nom, "entite": ent, "domaine": dom,
                    "moments": set(d.get("moments", ["soir"]))})
    return out


class PresenceSimulator:
    def __init__(self, home, zones: list, store,
                 horloge: "Callable[[], datetime]" = datetime.now,
                 hasard: "Callable[[], float]" = None):
        import random
        self.home = home
        self.zones = zones
        self.store = store
        self.horloge = horloge
        self.hasard = hasard or random.random
        self._applique: dict = {}
        self.store.data.setdefault("vacances", False)

    @property
    def arme(self) -> bool:
        return bool(self.store.data.get("vacances"))

    def armer(self) -> str:
        self.store.data["vacances"] = True
        self.store.save()
        return "🏖️ Mode vacances armé : je simulerai une présence (sans jamais déverrouiller)."

    def desarmer(self) -> str:
        self.store.data["vacances"] = False
        self.store.save()
        return "Mode vacances désarmé."

    def etat(self) -> str:
        return ("Simulation de présence ACTIVE." if self.arme
                else "Simulation de présence désactivée.")

    def tic(self) -> dict:
        """Un pas de simulation : ajuste chaque zone selon le moment + un aléa. Renvoie les changements."""
        if not self.arme or not self.zones:
            return {}
        mmt = moment(self.horloge().hour)
        changements = {}
        for z in self.zones:
            if self.hasard() < _SAUT:        # variation : on laisse parfois la zone telle quelle
                continue
            allume = mmt in z["moments"]
            cible = "on" if allume else "off"
            if self._applique.get(z["nom"]) == cible:
                continue
            on_svc, off_svc = _SERVICES[z["domaine"]]
            try:
                self.home.call(z["domaine"], on_svc if allume else off_svc, z["entite"])
            except Exception:
                log.exception("simulation : %s", z["nom"])
                continue
            self._applique[z["nom"]] = cible
            changements[z["nom"]] = cible
        return changements


def build_simulation_tools(home) -> list:
    from tools import Tool

    if not (config.SIM and zones_config()):
        return []
    sim = _simulateur(home)
    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="armer_vacances",
             description="Arme la simulation de présence (mode vacances) : lumières/volets rejoués avec variation.",
             parameters=vide, run=lambda: sim.armer()),
        Tool(name="desarmer_vacances", description="Désarme la simulation de présence.",
             parameters=vide, run=lambda: sim.desarmer()),
        Tool(name="etat_vacances", description="Dit si la simulation de présence est active.",
             parameters=vide, run=lambda: sim.etat()),
    ]


_SIM: "PresenceSimulator | None" = None


def _simulateur(home) -> PresenceSimulator:
    global _SIM
    from skills import JsonStore
    if _SIM is None:
        _SIM = PresenceSimulator(home, zones_config(), JsonStore(config.SIM_FILE, {}))
    return _SIM


class PresenceWatcher(threading.Thread):
    def __init__(self, sim: PresenceSimulator, interval_s: float = 300.0):
        super().__init__(daemon=True, name="jarvis-presence-sim")
        self.sim = sim
        self.interval_s = interval_s
        self._halt = threading.Event()

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            try:
                self.sim.tic()
            except Exception:
                log.exception("boucle de simulation")

    def arreter(self) -> None:
        self._halt.set()


def make_presence_watcher(home) -> "PresenceWatcher | None":
    if not (config.SIM and zones_config()):
        return None
    return PresenceWatcher(_simulateur(home), interval_s=config.SIM_INTERVALLE)
