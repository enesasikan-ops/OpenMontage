"""Journal des personnes vues — pour pouvoir DEMANDER « qui as-tu vu ? ».

Double Take (via CompreFace, en local) publie le nom reconnu sur MQTT ; arrivals.py
l'annonce en direct. Ce module garde en plus une courte mémoire des dernières personnes
vues, pour que tu puisses interroger Jarvis après coup.

Respect de la ligne tenue : on n'enregistre que ce que Double Take a déjà reconnu (des
visages que TU as enrôlés) ou « un inconnu » — jamais d'identification de tiers. C'est un
journal court et glissant (en mémoire), pas une archive de surveillance.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Callable


def _depuis(dt: datetime, maintenant: datetime) -> str:
    m = int((maintenant - dt).total_seconds() // 60)
    if m < 1:
        return "à l'instant"
    if m < 60:
        return f"il y a {m} min"
    return f"il y a {m // 60} h"


class SightingLog:
    def __init__(self, taille: int = 50, horloge: "Callable[[], datetime]" = datetime.now):
        self._vus = deque(maxlen=taille)
        self.horloge = horloge

    def noter(self, nom: "str | None", camera: str, connu: bool) -> None:
        self._vus.append({"nom": nom, "camera": camera, "connu": connu, "quand": self.horloge()})

    def recents(self, n: int = 5) -> list:
        return list(self._vus)[-n:][::-1]

    def resume(self, n: int = 5) -> str:
        recents = self.recents(n)
        if not recents:
            return "Je n'ai vu personne récemment."
        maintenant = self.horloge()
        morceaux = []
        for v in recents:
            qui = v["nom"].capitalize() if v["connu"] and v["nom"] else "un inconnu"
            lieu = f" ({v['camera']})" if v["camera"] else ""
            morceaux.append(f"{qui}{lieu}, {_depuis(v['quand'], maintenant)}")
        return "Dernières personnes vues : " + " ; ".join(morceaux) + "."


_JOURNAL: "SightingLog | None" = None


def journal() -> SightingLog:
    global _JOURNAL
    if _JOURNAL is None:
        _JOURNAL = SightingLog()
    return _JOURNAL


def build_sighting_tools() -> list:
    from tools import Tool

    return [Tool(
        name="qui_as_tu_vu",
        description=("Dit quelles personnes les caméras ont reconnues récemment (Double Take / "
                     "CompreFace). « qui as-tu vu ? », « qui est passé ? ». Lecture seule."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=lambda: journal().resume(),
    )]
