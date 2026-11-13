"""Arroseur anti-nuisibles : dissuasion par zone, jamais du ciblage.

« Jarvis, arrose le parterre. » → ouvre l'eau sur une ZONE quelques secondes, comme un
arroseur à détection du commerce. Pour un déclenchement automatique sur détection d'animal,
on crée une automatisation Home Assistant (capteur animal → cet arroseur).

Volontairement SANS visée ni coordonnées d'une cible vivante : on arrose un parterre, on ne
« tire » pas sur un animal. Pas de tourelle, pas d'arme.
"""

from __future__ import annotations

import threading

import config


def _norm(t: str) -> str:
    return (t or "").strip().lower()


class Sprinkler:
    def __init__(self, home, zones: dict | None = None, planifier=None):
        self.home = home
        self.zones = {_norm(k): str(v) for k, v in (zones or {}).items()}
        # planifier(secondes, fonction) : par défaut un minuteur (coupe l'eau après coup).
        self._planifier = planifier or (lambda s, f: threading.Timer(s, f).start())

    def _entite(self, zone: str) -> "str | None":
        z = _norm(zone)
        if z in self.zones:
            return self.zones[z]
        for nom, ent in self.zones.items():
            if nom in z or z in nom:
                return ent
        return None

    def arroser(self, zone: str = "", secondes: float = 8) -> str:
        if not self.zones:
            return "Aucun arroseur configuré (JARVIS_ARROSEUR)."
        ent = self._entite(zone) if zone else next(iter(self.zones.values()))
        if ent is None:
            connues = ", ".join(sorted(self.zones))
            return f"Je ne connais pas la zone « {zone} ». Zones : {connues}."
        secondes = max(1.0, min(float(secondes), 60.0))   # jamais plus d'une minute d'eau
        self.home.call("switch", "turn_on", ent)
        self._planifier(secondes, lambda: self.home.call("switch", "turn_off", ent))
        ou = f"le {zone}" if zone else "le jardin"
        return f"J'arrose {ou} pendant {int(secondes)} secondes."


def build_deterrent_tools(home, zones: dict | None = None) -> list:
    from tools import Tool

    sp = Sprinkler(home, zones if zones is not None else config.ARROSEUR_ZONES)
    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [Tool(
        name="arroser",
        description=("Déclenche l'arroseur sur une zone du jardin quelques secondes (dissuasion "
                     "des animaux, parterres). « Arrose le parterre »."),
        parameters=obj({"zone": {**s, "description": "la zone à arroser (ex. parterre, potager)"},
                        "secondes": {"type": "number", "description": "durée (défaut 8, max 60)"}}, []),
        run=lambda zone="", secondes=8: sp.arroser(zone, secondes),
    )]
