"""La voiture comme nœud de Jarvis — par la voie SUPPORTÉE, pas par le bus CAN.

Jarvis étend sa veille au véhicule via l'API voiture connectée du constructeur, exposée
dans Home Assistant (Tesla, Hyundai/Kia, Toyota, VW, Renault…) : position GPS, état des
serrures, carburant/charge/autonomie, et (si la voiture le fournit) une alerte « quelqu'un
rôde » depuis son mode sentinelle. Il peut verrouiller à distance.

Ligne tenue (comme pour la maison) : lire est libre ; DÉVERROUILLER à distance est une
action sensible → confirmation. On NE touche PAS au bus CAN ni à la conduite : aucun lien
entre l'IA et les commandes du véhicule (direction, freins). Lire une télémétrie officielle
n'est pas piloter la voiture.
"""

from __future__ import annotations

import config


class Vehicle:
    def __init__(self, home, tracker: str = "", serrure: str = "", capteurs: "dict | None" = None):
        self.home = home
        self.tracker = tracker
        self.serrure = serrure
        self.capteurs = capteurs or {}

    def _etats(self) -> dict:
        try:
            return {e["entity_id"]: e for e in self.home.states()}
        except Exception:
            return {}

    def localiser(self) -> str:
        if not self.tracker:
            return "Je n'ai pas la position de la voiture (configure JARVIS_VOITURE_POSITION)."
        e = self._etats().get(self.tracker)
        if not e:
            return "Je n'arrive pas à lire la position de la voiture."
        etat = e.get("state", "?")
        attrs = e.get("attributes", {})
        lieu = {"home": "à la maison", "not_home": "en déplacement"}.get(etat, etat)
        lat, lon = attrs.get("latitude"), attrs.get("longitude")
        coords = f" (≈ {lat}, {lon})" if lat is not None and lon is not None else ""
        return f"La voiture est {lieu}{coords}, Monsieur."

    def etat(self) -> str:
        etats = self._etats()
        bouts = []
        if self.serrure and self.serrure in etats:
            verr = etats[self.serrure].get("state", "?")
            bouts.append("verrouillée" if verr == "locked" else "DÉVERROUILLÉE" if verr == "unlocked" else verr)
        for label, ent in self.capteurs.items():
            if ent in etats and etats[ent].get("state") not in (None, "unknown", "unavailable"):
                bouts.append(f"{label} : {etats[ent]['state']}")
        if not bouts:
            return "Je n'ai pas d'information sur la voiture pour l'instant."
        return "Voiture — " + ", ".join(bouts) + "."

    def verrouiller(self) -> str:
        if not self.serrure:
            return "Aucune serrure de voiture configurée."
        try:
            self.home.call("lock", "lock", self.serrure)
        except Exception:
            return "Je n'arrive pas à joindre la voiture."
        return "Voiture verrouillée, Monsieur."

    def deverrouiller(self) -> str:
        if not self.serrure:
            return "Aucune serrure de voiture configurée."
        try:
            self.home.call("lock", "unlock", self.serrure)
        except Exception:
            return "Je n'arrive pas à joindre la voiture."
        return "Voiture déverrouillée."


def build_vehicle_tools(home) -> list:
    from tools import Tool

    if not config.VEHICLE or not (config.VEHICLE_TRACKER or config.VEHICLE_LOCK or config.VEHICLE_SENSORS):
        return []
    v = Vehicle(home, config.VEHICLE_TRACKER, config.VEHICLE_LOCK, config.VEHICLE_SENSORS)
    vide = {"type": "object", "properties": {}, "required": []}

    return [
        Tool(name="localiser_voiture",
             description="Dit où se trouve la voiture (position GPS via l'API constructeur). Lecture seule.",
             parameters=vide, run=lambda: v.localiser()),
        Tool(name="etat_voiture",
             description="État de la voiture : serrures, carburant/charge/autonomie. Lecture seule.",
             parameters=vide, run=lambda: v.etat()),
        Tool(name="verrouiller_voiture", description="Verrouille la voiture à distance.",
             parameters=vide, run=lambda: v.verrouiller()),
        Tool(name="deverrouiller_voiture", description="Déverrouille la voiture à distance.",
             parameters=vide, run=lambda: v.deverrouiller(),
             confirm=lambda: "Je vais DÉVERROUILLER la voiture à distance."),
    ]
