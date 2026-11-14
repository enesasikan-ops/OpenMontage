"""Annonces d'arrivée : Jarvis écoute les caméras (Frigate / Double Take) via MQTT.

Frigate détecte les personnes, Double Take reconnaît QUI c'est, et ils publient un
message sur MQTT (le standard de l'IoT). Jarvis s'y abonne et annonce l'arrivée dans sa
voix : visage connu → annonce naturelle ; inconnu → alerte formelle.

L'annonce par défaut est un modèle (instantané, fiable, dans le ton de Jarvis). Le texte
est volontairement séparé de l'écoute MQTT, pour être testable sans caméra ni serveur.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import persona

log = logging.getLogger(__name__)

COOLDOWN_S = 60  # une même personne n'est pas ré-annoncée avant ce délai


def _position(camera: str) -> str:
    c = (camera or "").lower()
    lieux = {
        "entree": "à la porte d'entrée", "entrée": "à la porte d'entrée", "porte": "à la porte",
        "garage": "près du garage", "jardin": "dans le jardin", "portail": "au portail",
        "allee": "dans l'allée", "allée": "dans l'allée", "porche": "sous le porche",
    }
    for cle, texte in lieux.items():
        if cle in c:
            return texte
    return f"près de la caméra {camera}" if camera else "sur la propriété"


def texte_arrivee(nom: "str | None", camera: str, connu: bool) -> str:
    """Formule l'annonce, dans le ton de Jarvis. Une à deux phrases."""
    titre = persona.title()
    ou = _position(camera)
    if connu and nom:
        return f"{titre}, {nom.capitalize()} est {ou}."
    return (f"{titre}, je détecte un individu non identifié {ou}. "
            "Dois-je activer l'éclairage de sécurité ?")


def _analyser(charge: bytes) -> "tuple[str | None, str, bool] | None":
    """Lit un message MQTT de Double Take/Frigate. Renvoie (nom, caméra, connu) ou None."""
    try:
        data = json.loads(charge.decode("utf-8", "ignore"))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    nom = data.get("name") or data.get("label") or ""
    camera = data.get("camera") or data.get("source") or ""
    inconnu = (not nom) or str(nom).lower() in ("unknown", "inconnu", "person", "personne")
    # Double Take fournit parfois match: false pour une correspondance trop faible.
    if data.get("match") is False:
        inconnu = True
    return (None if inconnu else str(nom), str(camera), not inconnu)


class ArrivalWatcher:
    """Écoute les événements caméra sur MQTT et déclenche `on_arrivee(nom, camera, connu)`."""

    def __init__(self, on_arrivee: "Callable[[str | None, str, bool], None]",
                 host: str = "localhost", port: int = 1883,
                 topic: str = "double-take/matches/#", username: str = "", password: str = "",
                 client=None):
        self.on_arrivee = on_arrivee
        self.host, self.port, self.topic = host, port, topic
        self.username, self.password = username, password
        self._client = client
        self._dernier: dict[str, float] = {}   # anti-répétition par personne

    def traiter(self, charge: bytes) -> None:
        """Point d'entrée testable : un message MQTT reçu."""
        resultat = _analyser(charge)
        if resultat is None:
            return
        nom, camera, connu = resultat
        cle = nom if connu else f"inconnu:{camera}"   # anti-répétition
        maintenant = time.monotonic()
        if maintenant - self._dernier.get(cle, 0.0) < COOLDOWN_S:
            return
        self._dernier[cle] = maintenant
        try:
            self.on_arrivee(nom, camera, connu)
        except Exception:
            log.exception("annonce d'arrivée")

    def demarrer(self) -> dict:
        if self._client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                return {"statut": "erreur",
                        "message": "paho-mqtt manquant. Installe-le : pip install paho-mqtt"}
            self._client = mqtt.Client()
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_message = lambda c, u, msg: self.traiter(msg.payload)
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.subscribe(self.topic)
        except OSError as exc:
            return {"statut": "erreur", "message": f"MQTT injoignable ({self.host}:{self.port}) : {exc}"}
        threading.Thread(target=self._client.loop_forever, name="jarvis-mqtt", daemon=True).start()
        log.info("👁️ Écoute des caméras sur MQTT %s:%d (%s)", self.host, self.port, self.topic)
        return {"statut": "succès", "message": f"À l'écoute des caméras ({self.topic})"}

    def arreter(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
