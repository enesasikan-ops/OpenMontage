"""Conscience de situation — relier tous les capteurs en une réflexion.

Jarvis perçoit beaucoup (heure, état de la maison, présence par pièce, visages reconnus,
ciel/drones, météo, sécurité réseau…). Ce module rassemble un INSTANTANÉ de ces
perceptions et demande au renfort d'en faire une brève RÉFLEXION de majordome : relier
les signaux, signaler ce qui mérite l'attention, proposer si pertinent.

Ligne tenue : il OBSERVE et RÉFLÉCHIT, il n'AGIT pas. Aucune action n'est déclenchée par
une réflexion — les actions sensibles restent derrière la confirmation habituelle. Les
perceptions sont celles des capteurs du propriétaire, chez lui ; rien n'est inventé.

VIE PRIVÉE (honnête) : la réflexion est confiée au RENFORT (Claude/Gemini), donc
l'instantané — état de la maison, qui est présent, ciel — SORT vers le cloud le temps de
raisonner. En mode hors-ligne, le renfort est absent et l'outil n'existe pas (rien ne
sort). Si tu veux la réflexion 100 % locale, c'est l'option « 2ᵉ modèle local » à brancher.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger("jarvis.conscience")

PROMPT = ("Voici l'état actuel de la maison et de son environnement, vu par mes capteurs. "
          "Fais une brève RÉFLEXION (ton majordome) : relie les signaux entre eux, signale "
          "ce qui mérite l'attention, et propose une action SEULEMENT si c'est pertinent — "
          "mais tu ne décides ni n'agis, tu éclaires. Si tout est normal, dis-le simplement. "
          "N'invente aucune donnée absente. Deux à quatre phrases.")

PROMPT_PROACTIF = ("Voici l'état actuel de la maison et de son environnement, vu par mes capteurs. "
                   "Dois-je DÉRANGER le propriétaire ? Réponds EXACTEMENT « RAS » (rien à signaler) "
                   "si tout est normal ou banal — c'est le cas le plus fréquent, n'hésite pas. "
                   "Signale quelque chose SEULEMENT si un signal, ou une combinaison de signaux, "
                   "mérite vraiment son attention (anomalie, oubli probable, risque). Alors une seule "
                   "phrase utile, qui propose sans agir. N'invente rien.")


class Conscience:
    def __init__(self, perceptions: dict, demander: "Callable[[str, str], str]"):
        self.perceptions = perceptions     # {nom: () -> str}
        self.demander = demander           # renfort : demander(question, contexte) -> str

    def percevoir(self) -> dict:
        """Appelle chaque source (tolérant aux pannes) et renvoie {nom: texte}."""
        instantane = {}
        for nom, source in self.perceptions.items():
            try:
                valeur = source()
            except Exception:
                continue
            if valeur:
                instantane[nom] = str(valeur).strip()
        return instantane

    def reflechir(self) -> str:
        instantane = self.percevoir()
        if not instantane:
            return "Je n'ai aucune perception exploitable pour l'instant."
        contexte = "\n".join(f"- {nom} : {v}" for nom, v in instantane.items())
        try:
            return self.demander(PROMPT, contexte)
        except Exception:
            return "Je n'arrive pas à faire le point (renfort indisponible)."

    def veille(self) -> str:
        """Réflexion PROACTIVE : renvoie un message seulement si ça mérite de déranger, sinon ''."""
        instantane = self.percevoir()
        if not instantane:
            return ""
        contexte = "\n".join(f"- {nom} : {v}" for nom, v in instantane.items())
        try:
            rep = (self.demander(PROMPT_PROACTIF, contexte) or "").strip()
        except Exception:
            log.warning("veille de conscience : renfort indisponible")
            return ""
        if rep.strip(" .!\"'«»").upper() == "RAS":
            return ""
        return rep


def _perceptions(home) -> dict:
    """Construit les sources de perception disponibles, chacune protégée."""
    import config
    p: dict = {}

    def _heure():
        from tools import _now_text
        return _now_text()
    p["heure"] = _heure

    if home is not None and getattr(home, "configured", False):
        p["maison"] = lambda: home.point_de_situation()

        def _presence():
            from presence import occupees, pieces_config
            pieces = pieces_config()
            if not pieces:
                return ""
            etats = {e["entity_id"]: e.get("state") for e in home.states()}
            occ = occupees(etats, pieces)
            return "occupées : " + (", ".join(sorted(occ)) if occ else "aucune (maison vide ?)")
        p["présence"] = _presence

    def _visages():
        from sightings import journal
        return journal().resume()
    p["caméras"] = _visages

    if config.DRONEWATCH:
        def _ciel():
            from dronewatch import journal
            return journal().resume()
        p["ciel"] = _ciel

    def _meteo():
        from skills import weather
        return weather()
    p["météo"] = _meteo

    return p


def build_conscience_tools(home, renfort) -> list:
    from tools import Tool

    ask = getattr(renfort, "ask", None)
    if not (callable(ask) and getattr(renfort, "available", False)):
        return []   # la réflexion s'appuie sur un bon raisonneur (renfort)
    c = Conscience(_perceptions(home), ask)

    return [Tool(
        name="fais_le_point",
        description=("Fait une réflexion générale sur la situation en reliant TOUS les capteurs "
                     "(heure, maison, présence, caméras, ciel, météo). Donne une lecture du moment "
                     "et propose si pertinent — il n'agit pas. « fais le point », « quoi de neuf ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=lambda: c.reflechir(),
    )]


# --- Réflexion proactive (Jarvis fait le point de lui-même, s'il a à dire) -----------


class ConscienceWatcher(threading.Thread):
    """Réfléchit à intervalle régulier et n'alerte QUE si ça mérite de déranger.

    Respecte les heures de silence (ne parle pas la nuit). Chaque tour envoie un
    instantané au renfort (cloud) : garde un intervalle large pour le coût et la vie privée.
    """

    def __init__(self, conscience: Conscience, notify: Callable[[str], None],
                 quiet: "Callable[[], bool]", interval_s: float = 1800.0):
        super().__init__(daemon=True, name="jarvis-conscience")
        self.conscience = conscience
        self.notify = notify
        self.quiet = quiet
        self.interval_s = interval_s
        self._halt = threading.Event()

    def un_tour(self) -> str:
        if self.quiet():
            return ""
        message = self.conscience.veille()
        if message:
            try:
                self.notify("💭 " + message)
            except Exception:
                log.exception("réflexion proactive")
        return message

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.un_tour()

    def arreter(self) -> None:
        self._halt.set()


def make_conscience_watcher(home, renfort, notify) -> "ConscienceWatcher | None":
    import config

    if not config.CONSCIENCE_PROACTIVE:
        return None
    ask = getattr(renfort, "ask", None)
    if not (callable(ask) and getattr(renfort, "available", False)):
        return None
    c = Conscience(_perceptions(home), ask)

    def _quiet() -> bool:
        from datetime import datetime

        from proactive import in_quiet_hours
        return in_quiet_hours(datetime.now())

    return ConscienceWatcher(c, notify, _quiet, interval_s=config.CONSCIENCE_INTERVAL)
