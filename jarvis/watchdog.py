"""Mode Sentinelle : réaction active anti-intrusion.

Quand TU l'armes, et qu'une caméra détecte un visage INCONNU, Jarvis réagit seul :
allume les lumières extérieures, (option) verrouille, lance un enregistrement, diffuse
une sommation vocale dissuasive, et t'alerte aussitôt.

C'est toi qui armes — donc la réaction est pré-autorisée, comme une alarme. Deux règles
non négociables :
- Jarvis n'appelle JAMAIS la police tout seul (les faux positifs existent ; une fausse
  alerte est illégale). Il t'alerte, TU décides.
- La sommation est VRAIE par défaut (« zone sous surveillance, vous êtes enregistré »),
  elle ne prétend pas que la police est prévenue.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger(__name__)

MESSAGE_DEFAUT = ("Vous êtes dans une zone sous surveillance. "
                  "Votre présence est enregistrée. Veuillez quitter les lieux.")


def _appeler(home, service: str, entity_id, **data) -> None:
    """Appelle un service Home Assistant « domaine.service »."""
    domaine, _, nom = (service or "").partition(".")
    if domaine and nom:
        home.call(domaine, nom, entity_id, **data)


class Watchdog:
    def __init__(self, home, notify: Callable[[str], None], store, settings: dict | None = None):
        self.home = home
        self.notify = notify
        self.store = store
        self.s = settings or {}
        self.store.data.setdefault("arme", False)

    @property
    def arme(self) -> bool:
        return bool(self.store.data.get("arme"))

    def armer(self) -> str:
        self.store.data["arme"] = True
        self.store.save()
        return "🛡️ Mode Sentinelle armé. Je surveille, Monsieur."

    def desarmer(self) -> str:
        self.store.data["arme"] = False
        self.store.save()
        return "Mode Sentinelle désarmé."

    def etat(self) -> str:
        return "Le mode Sentinelle est armé." if self.arme else "Le mode Sentinelle est désarmé."

    def declencher(self, message: str) -> list[str]:
        """Lance la réaction active (lumières, verrou, enregistrement, sommation) + alerte. Si armé."""
        if not self.arme:
            return []
        faites = []
        lumieres = self.s.get("lumieres") or []
        if lumieres:
            self._sur(lambda: self.home.call("light", "turn_on", lumieres), "lumières extérieures", faites)
        if self.s.get("verrouiller") and self.s.get("serrures"):
            self._sur(lambda: self.home.call("lock", "lock", self.s["serrures"]), "portes verrouillées", faites)
        if self.s.get("enregistrement_service"):
            self._sur(lambda: _appeler(self.home, self.s["enregistrement_service"],
                                       self.s.get("enregistrement_entite")), "enregistrement", faites)
        if self.s.get("haut_parleur"):
            annonce = self.s.get("message") or MESSAGE_DEFAUT
            self._sur(lambda: _appeler(self.home, self.s.get("tts_service", "tts.google_translate_say"),
                                       self.s["haut_parleur"], message=annonce), "sommation vocale", faites)
        self.notify(message + (f" Réaction : {', '.join(faites)}." if faites else ""))
        return faites

    def sur_intrusion(self, nom, camera: str, connu: bool) -> list[str]:
        """Détection caméra. N'agit QUE si armé ET visage inconnu."""
        if connu:
            return []
        zone = f" ({camera})" if camera else ""
        return self.declencher(f"🚨 INTRUSION{zone} : individu non identifié pendant que la Sentinelle "
                               "est armée. Si c'est une vraie intrusion, appelez la police.")

    def sur_son(self, nom_fr: str) -> list[str]:
        """Son suspect entendu (bris de glace…). N'agit QUE si armé."""
        return self.declencher(f"🚨 {nom_fr.capitalize()} détecté, hors du champ des caméras. "
                               "Si c'est une vraie intrusion, appelez la police.")

    @staticmethod
    def _sur(action: Callable, libelle: str, faites: list) -> None:
        try:
            action()
            faites.append(libelle)
        except Exception:
            log.exception("Sentinelle : %s", libelle)


def build_watchdog_tools(watchdog: Watchdog) -> list:
    from tools import Tool

    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="armer_surveillance",
             description="Arme le mode Sentinelle (réaction active si intrus pendant l'absence).",
             parameters=vide, run=lambda: watchdog.armer()),
        Tool(name="desarmer_surveillance",
             description="Désarme le mode Sentinelle.",
             parameters=vide, run=lambda: watchdog.desarmer()),
        Tool(name="etat_surveillance",
             description="Dit si le mode Sentinelle est armé ou non.",
             parameters=vide, run=lambda: watchdog.etat()),
    ]
