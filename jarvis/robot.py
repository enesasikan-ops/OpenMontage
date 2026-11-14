"""Pont vers un robot mobile (ROS 2 / Nav2), en local.

« Jarvis, va au garage. » → Jarvis envoie une DESTINATION NOMMÉE au robot (par MQTT). Le
robot, qui tourne sous ROS 2 avec sa carte (SLAM) et sa navigation (Nav2), se débrouille
pour y aller en évitant les obstacles. Jarvis ne fait pas la navigation : il donne l'ordre.

C'est volontairement une interface simple et découplée : Jarvis n'embarque pas ROS 2.
Un petit nœud ROS sur le robot écoute ces messages et les traduit en objectifs Nav2.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

import config

log = logging.getLogger(__name__)


def _norm(t: str) -> str:
    return (t or "").strip().lower()


class RobotCourier:
    def __init__(self, lieux, publier: "Callable | None" = None,
                 topic: str = "jarvis/robot/commande"):
        self.lieux = {_norm(x) for x in lieux}
        self.topic = topic
        self._publier = publier or self._mqtt   # publier(topic, payload_str)

    def _mqtt(self, topic: str, payload: str) -> None:
        import paho.mqtt.publish as publish
        auth = {"username": config.MQTT_USER, "password": config.MQTT_PASS} if config.MQTT_USER else None
        publish.single(topic, payload, hostname=config.MQTT_HOST, port=config.MQTT_PORT, auth=auth)

    def _commande(self, action: str, lieu: str = "") -> str:
        try:
            self._publier(self.topic, json.dumps({"action": action, "destination": lieu}))
        except Exception as exc:
            log.error("commande robot : %s", exc)
            return "Je n'arrive pas à joindre le robot."
        return ""

    def aller(self, lieu: str) -> str:
        z = _norm(lieu)
        if z not in self.lieux:
            connus = ", ".join(sorted(self.lieux)) or "aucun lieu configuré"
            return f"Je ne connais pas le lieu « {lieu} ». Destinations : {connus}."
        err = self._commande("aller", z)
        return err or f"J'envoie le robot au {lieu}, Monsieur."

    def revenir(self) -> str:
        return self._commande("retour") or "Le robot rentre à sa base."

    def arreter(self) -> str:
        return self._commande("stop") or "J'arrête le robot."


def build_robot_tools(lieux=None) -> list:
    from tools import Tool

    lieux = lieux if lieux is not None else config.ROBOT_LIEUX
    if not lieux:
        return []
    courier = RobotCourier(lieux)
    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [
        Tool(name="envoyer_robot",
             description="Envoie le robot mobile à un lieu nommé de la maison (garage, salon…). Il navigue seul.",
             parameters=obj({"lieu": {**s, "description": "la destination (ex. garage, cuisine)"}}, ["lieu"]),
             run=lambda lieu: courier.aller(lieu)),
        Tool(name="rappeler_robot", description="Renvoie le robot mobile à sa base.",
             parameters=obj({}, []), run=lambda: courier.revenir()),
        Tool(name="arreter_robot", description="Arrête le robot mobile tout de suite.",
             parameters=obj({}, []), run=lambda: courier.arreter()),
    ]
