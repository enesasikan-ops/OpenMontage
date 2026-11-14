"""Veille aérienne — détection de drones par Remote ID / OpenDroneID.

Un récepteur dédié (OpenDroneID en Bluetooth/Wi-Fi, ou un décodeur SDR) capte les paquets
que la plupart des drones civils diffusent EN CLAIR par obligation légale, et les publie
sur MQTT. Jarvis les écoute et t'alerte qu'un drone survole la propriété.

LIGNE TENUE (défense, pas justice privée) :
- On DÉTECTE et on ALERTE : « un drone survole la zone ». Recevoir ces diffusions est légal.
- La position de l'OPÉRATEUR (diffusée par le drone) est une donnée d'une PERSONNE. Jarvis la
  consigne comme PREUVE (pour un dépôt de plainte éventuel), il n'en fait PAS un outil pour
  localiser ou confronter quelqu'un. L'alerte invite à noter et à prévenir la police, pas à agir.
- Ne voit que les drones CONFORMES (qui émettent un Remote ID) ; un drone muet passe inaperçu.
  Ce n'est pas un dôme étanche, c'est une veille.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable

log = logging.getLogger("jarvis.aerien")


def _champ(d: dict, *cles, defaut=None):
    for c in cles:
        if c in d and d[c] not in (None, ""):
            return d[c]
    return defaut


def analyser(charge: bytes) -> "dict | None":
    """Normalise un message de détection OpenDroneID/Remote ID. Renvoie un dict ou None."""
    try:
        d = json.loads(charge.decode("utf-8", "ignore"))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None
    if not isinstance(d, dict):
        return None
    ident = _champ(d, "uas_id", "basic_id", "id", "serial", defaut="drone inconnu")
    lat = _champ(d, "lat", "latitude", "drone_lat")
    lon = _champ(d, "lon", "longitude", "drone_lon")
    if lat is None or lon is None:
        return None
    return {
        "id": str(ident),
        "lat": lat, "lon": lon,
        "altitude": _champ(d, "alt", "altitude", "geodetic_altitude", "height", defaut="?"),
        "operateur_lat": _champ(d, "operator_lat", "pilot_lat", "system_lat"),
        "operateur_lon": _champ(d, "operator_lon", "pilot_lon", "system_lon"),
    }


def message(det: dict) -> str:
    return (f"🚁 Drone détecté au-dessus de la zone (altitude ~{det.get('altitude', '?')} m). "
            "Détection enregistrée. Si cette présence vous gêne, notez l'heure et prévenez la police.")


def _preuve(det: dict) -> str:
    op = ""
    if det.get("operateur_lat") is not None and det.get("operateur_lon") is not None:
        op = f" ; opérateur signalé vers {det['operateur_lat']},{det['operateur_lon']}"
    return (f"drone {det['id']} au-dessus (alt {det.get('altitude', '?')} m, "
            f"pos {det['lat']},{det['lon']}{op})")


class DroneLog:
    def __init__(self, taille: int = 50, horloge: "Callable[[], datetime]" = datetime.now):
        self._vus = deque(maxlen=taille)
        self.horloge = horloge

    def noter(self, det: dict) -> None:
        self._vus.append({**det, "quand": self.horloge()})

    def recents(self, n: int = 5) -> list:
        return list(self._vus)[-n:][::-1]

    def resume(self, n: int = 5) -> str:
        recents = self.recents(n)
        if not recents:
            return "Aucun drone détecté récemment. Ciel calme."
        lignes = []
        for d in recents:
            h = d["quand"].strftime("%H:%M") if hasattr(d["quand"], "strftime") else "?"
            op = ""
            if d.get("operateur_lat") is not None:
                op = f", opérateur signalé vers {d['operateur_lat']},{d['operateur_lon']} (enregistré)"
            lignes.append(f"{h} — drone {d['id']} à ~{d.get('altitude', '?')} m{op}")
        return "Drones détectés (enregistrés comme preuve) :\n" + "\n".join(f"- {x}" for x in lignes)


_LOG: "DroneLog | None" = None


def journal() -> DroneLog:
    global _LOG
    if _LOG is None:
        _LOG = DroneLog()
    return _LOG


class DroneWatcher:
    def __init__(self, notify: Callable[[str], None], evidence=None, horloge=time.monotonic,
                 cooldown_s: float = 120.0, host="localhost", port=1883,
                 topic="opendroneid/#", username="", password="", client=None):
        self.notify = notify
        self.evidence = evidence
        self.horloge = horloge
        self.cooldown_s = cooldown_s
        self.host, self.port, self.topic = host, port, topic
        self.username, self.password = username, password
        self._client = client
        self._dernier: dict = {}

    def traiter(self, charge: bytes) -> None:
        det = analyser(charge)
        if det is None:
            return
        maintenant = self.horloge()
        if maintenant - self._dernier.get(det["id"], -1e18) < self.cooldown_s:
            return
        self._dernier[det["id"]] = maintenant
        journal().noter(det)
        if self.evidence is not None:
            try:
                self.evidence.consigner(_preuve(det))
            except Exception:
                log.exception("journal de preuves drone")
        try:
            self.notify(message(det))
        except Exception:
            log.exception("alerte drone")

    def demarrer(self) -> dict:
        if self._client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                return {"statut": "erreur", "message": "paho-mqtt manquant"}
            self._client = mqtt.Client()
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_message = lambda c, u, msg: self.traiter(msg.payload)
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.subscribe(self.topic)
        except OSError as exc:
            return {"statut": "erreur", "message": f"MQTT injoignable : {exc}"}
        threading.Thread(target=self._client.loop_forever, name="jarvis-aerien", daemon=True).start()
        return {"statut": "succès", "message": "Veille aérienne active"}


def build_drone_tools() -> list:
    from tools import Tool

    import config
    if not config.DRONEWATCH:
        return []
    return [Tool(
        name="point_aerien",
        description=("Dit quels drones ont survolé la propriété récemment (Remote ID). "
                     "« y a-t-il eu des drones ? », « point aérien ». Lecture seule."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=lambda: journal().resume(),
    )]


def make_drone_watcher(notify, evidence=None) -> "DroneWatcher | None":
    import config
    if not config.DRONEWATCH:
        return None
    return DroneWatcher(notify, evidence=evidence, cooldown_s=config.DRONE_COOLDOWN,
                        host=config.MQTT_HOST, port=config.MQTT_PORT, topic=config.DRONE_TOPIC,
                        username=config.MQTT_USER, password=config.MQTT_PASS)
