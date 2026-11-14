"""Battement de cœur — le « détecteur d'homme mort » de Jarvis.

Jarvis ne peut PAS « survivre dans les ampoules » (voir pourquoi plus bas) : son cerveau
est un gros modèle qui tourne sur un vrai ordinateur. Ce qu'on peut faire, c'est le
rendre RÉSILIENT : tant qu'il est vivant, il publie un battement régulier sur MQTT. Un
veilleur INDÉPENDANT (une automatisation Home Assistant, ou une puce ESPHome — surtout
pas du code DANS Jarvis, qui serait mort avec lui) surveille ce battement. S'il s'arrête
(serveur éteint, détruit, débranché), le veilleur bascule la maison en mode sûr :
allumer, armer, alerter par un canal indépendant (cellulaire).

Côté Home Assistant, c'est un `binary_sensor` MQTT avec `expire_after` :

    binary_sensor:
      - name: "Jarvis vivant"
        state_topic: "jarvis/coeur"
        payload_on: "online"
        expire_after: 90          # pas de battement depuis 90 s -> 'off'
    # puis une automation : quand 'Jarvis vivant' passe à off -> lumières + sirène + SMS 4G

Ce module ne fait qu'une chose : émettre le battement tant que Jarvis vit. La RÉACTION
vit dehors, par nécessité.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

import config

log = logging.getLogger("jarvis.coeur")


class HeartbeatEmitter(threading.Thread):
    def __init__(self, publier: "Callable | None" = None, topic: str = "jarvis/coeur",
                 interval_s: float = 30.0, charge: str = "online"):
        super().__init__(daemon=True, name="jarvis-coeur")
        self.topic = topic
        self.interval_s = interval_s
        self.charge = charge
        self._publier = publier or self._mqtt      # publier(topic, charge, retain)
        self._halt = threading.Event()

    def _mqtt(self, topic: str, charge: str, retain: bool) -> None:
        import paho.mqtt.publish as publish

        auth = {"username": config.MQTT_USER, "password": config.MQTT_PASS} if config.MQTT_USER else None
        publish.single(topic, charge, hostname=config.MQTT_HOST, port=config.MQTT_PORT,
                       auth=auth, retain=retain)

    def battement(self) -> bool:
        try:
            self._publier(self.topic, self.charge, True)   # retained : un abonné tardif voit l'état
            return True
        except Exception:
            log.warning("battement de cœur non publié (MQTT injoignable ?)")
            return False

    def demarrer(self) -> None:
        self.battement()      # un premier battement tout de suite
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.battement()

    def arreter(self) -> None:
        self._halt.set()


def make_heartbeat() -> "HeartbeatEmitter | None":
    if not config.HEARTBEAT:
        return None
    return HeartbeatEmitter(topic=config.HEARTBEAT_TOPIC, interval_s=config.HEARTBEAT_INTERVAL)
