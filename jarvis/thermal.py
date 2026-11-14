"""Vigilance thermique — la plaque oubliée (caméra thermique MLX90640 via ESPHome).

Une mini-caméra thermique (MLX90640, ~30 €) sur un ESP32 publie, via ESPHome, la
température d'une zone (ex. le maximum vu au-dessus de la plaque de cuisson). Jarvis
surveille : si une zone reste chaude alors que la maison est « endormie » (heures de
silence) ou que tu l'as armée, il te prévient — « vous avez oublié d'éteindre la plaque ».

HONNÊTETÉ :
- Le MLX90640 mesure une température de SURFACE dans son champ, pas une vérité absolue :
  sa précision se dégrade dans les hautes températures, et nommer « plaque GAUCHE »
  suppose que le capteur (ou une zone de l'image) vise bien cet endroit. On rapporte la
  température mesurée, on ne l'invente pas.
- On exige que ce soit CHAUD ET DURABLE (plusieurs minutes) avant d'alerter, pour ne pas
  crier à chaque fois que tu cuisines. Mieux vaut une alerte tardive qu'une fausse à midi.
- C'est une alerte de plus ; elle ne remplace pas un coupe-circuit ni ta vigilance.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import config

log = logging.getLogger("jarvis.thermique")


@dataclass(frozen=True)
class ThermalZone:
    nom: str
    capteur: str          # entity_id du capteur de température (°C)
    seuil: float          # au-dessus = « chaud »
    duree: float          # secondes au-dessus du seuil avant d'alerter


def zones_config() -> list:
    out = []
    for nom, d in (config.THERMAL_ZONES or {}).items():
        if isinstance(d, dict) and d.get("capteur"):
            out.append(ThermalZone(nom=nom, capteur=d["capteur"],
                                   seuil=float(d.get("seuil", 70)),
                                   duree=float(d.get("duree", config.THERMAL_DUREE))))
    return out


def _temp(valeur) -> "float | None":
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


class ThermalGuard:
    def __init__(self, zones: list, horloge: "Callable[[], float]" = None):
        import time
        self.zones = list(zones)
        self.horloge = horloge or time.monotonic
        self._chaud_depuis: dict = {}
        self._alertee: dict = {}

    def verifier(self, etats: dict, actif: bool) -> list:
        """Renvoie les NOUVELLES alertes [(nom, temp)] : zone chaude, durable, et vigilance active."""
        maintenant = self.horloge()
        alertes = []
        for z in self.zones:
            temp = _temp(etats.get(z.capteur))
            if temp is None:                      # capteur indisponible : on ne suppose rien
                continue
            if temp >= z.seuil:
                self._chaud_depuis.setdefault(z.nom, maintenant)
                assez = maintenant - self._chaud_depuis[z.nom] >= z.duree
                if actif and assez and not self._alertee.get(z.nom):
                    self._alertee[z.nom] = True
                    alertes.append((z.nom, temp))
            else:                                 # refroidi : on réarme pour le prochain épisode
                self._chaud_depuis.pop(z.nom, None)
                self._alertee[z.nom] = False
        return alertes

    def etat_zones(self, etats: dict) -> list:
        out = []
        for z in self.zones:
            temp = _temp(etats.get(z.capteur))
            out.append((z.nom, temp, temp is not None and temp >= z.seuil))
        return out


def message_alerte(nom: str, temp: float) -> str:
    import persona
    return (f"{persona.title()}, la zone « {nom} » est toujours chaude "
            f"({temp:.0f} °C). Avez-vous oublié de l'éteindre ?")


# --- Veille (fil) -------------------------------------------------------------------


class ThermalWatcher(threading.Thread):
    def __init__(self, home, guard: ThermalGuard, notify: Callable[[str], None],
                 actif: "Callable[[], bool]", interval_s: float = 30.0, evidence=None):
        super().__init__(daemon=True, name="jarvis-thermique")
        self.home = home
        self.guard = guard
        self.notify = notify
        self.actif = actif
        self.interval_s = interval_s
        self.evidence = evidence
        self._halt = threading.Event()

    def un_tour(self) -> list:
        try:
            etats = {e["entity_id"]: e.get("state") for e in self.home.states()}
        except Exception:
            log.exception("lecture des capteurs thermiques")
            return []
        alertes = self.guard.verifier(etats, self.actif())
        for nom, temp in alertes:
            if self.evidence is not None:
                try:
                    self.evidence.consigner(f"zone chaude oubliée : {nom} ({temp:.0f} °C)")
                except Exception:
                    log.exception("journal de preuves thermique")
            try:
                self.notify("🔥 " + message_alerte(nom, temp))
            except Exception:
                log.exception("alerte thermique")
        return alertes

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.un_tour()

    def arreter(self) -> None:
        self._halt.set()


def _vigilance_active(home) -> bool:
    """Par défaut : la nuit (heures de silence), ou si un interrupteur de vigilance est armé."""
    from proactive import in_quiet_hours

    if in_quiet_hours(datetime.now()):
        return True
    arme = config.THERMAL_ARME_ENTITE
    if arme:
        try:
            for e in home.states():
                if e["entity_id"] == arme:
                    return e.get("state") == "on"
        except Exception:
            pass
    return False


# Garde partagée entre l'outil (lecture) et la veille.
_GUARD: "ThermalGuard | None" = None


def guard() -> "ThermalGuard | None":
    global _GUARD
    if not (config.THERMAL and config.THERMAL_ZONES):
        return None
    if _GUARD is None:
        zones = zones_config()
        _GUARD = ThermalGuard(zones) if zones else None
    return _GUARD


def build_thermal_tools(home) -> list:
    from tools import Tool

    g = guard()
    if g is None:
        return []

    def point_thermique() -> str:
        try:
            etats = {e["entity_id"]: e.get("state") for e in home.states()}
        except Exception:
            return "Je n'arrive pas à lire les capteurs thermiques."
        lignes = []
        for nom, temp, chaud in g.etat_zones(etats):
            if temp is None:
                lignes.append(f"{nom} : indisponible")
            else:
                lignes.append(f"{nom} : {temp:.0f} °C{' ⚠️ chaud' if chaud else ''}")
        return "Zones thermiques — " + " ; ".join(lignes) + "."

    return [Tool(
        name="point_thermique",
        description=("Donne la température des zones surveillées par la caméra thermique "
                     "(« la plaque est-elle éteinte ? », « point thermique »). Lecture seule."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=point_thermique,
    )]


def make_thermal_watcher(home, notify, evidence=None) -> "ThermalWatcher | None":
    g = guard()
    if g is None:
        return None
    return ThermalWatcher(home, g, notify, actif=lambda: _vigilance_active(home),
                          interval_s=config.THERMAL_INTERVAL, evidence=evidence)
