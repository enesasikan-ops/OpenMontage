"""L'ouïe de Jarvis : classification des sons (YAMNet), en local.

Un micro écoute ; un réseau de neurones (YAMNet) reconnaît des bruits : bris de glace,
alarme incendie, pleurs de bébé, cri… Sur un son surveillé, Jarvis t'alerte (et, si la
Sentinelle est armée, déclenche la réaction active).

YAMNet (TensorFlow) est optionnel et lourd à installer, mais léger à faire tourner sur CPU.
La logique (correspondance, seuil, anti-répétition) est séparée du modèle, donc testable
sans micro ni TensorFlow.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

# Étiquettes YAMNet (anglais, sous-chaîne) -> nom français. Sons utiles à la maison.
SONS = {
    "glass": "bris de glace", "shatter": "bris de glace",
    "smoke detector": "alarme incendie", "fire alarm": "alarme incendie",
    "smoke alarm": "alarme incendie",
    "gunshot": "coup de feu", "gunfire": "coup de feu",
    "baby cry": "pleurs de bébé", "infant cry": "pleurs de bébé",
    "screaming": "cri", "shout": "cri", "yell": "cri",
    "civil defense siren": "sirène", "siren": "sirène",
    "alarm": "alarme", "smoke": "alarme incendie",
    "bark": "aboiement",
    # Classes typiques d'un modèle TinyML d'effraction (Edge Impulse sur ESP32) :
    "kick": "coup dans une porte", "door_break": "porte forcée", "break": "effraction",
    "pry": "porte forcée", "distress": "aboiement de détresse",
}
SEUIL = 0.5
COOLDOWN_S = 30


def _reconnaitre(label: str) -> "str | None":
    el = (label or "").lower()
    for cle, fr in SONS.items():
        if cle in el:
            return fr
    return None


class SoundWatcher:
    def __init__(self, on_son: Callable[[str, str, float], None],
                 seuil: float = SEUIL, classer: "Callable | None" = None):
        self.on_son = on_son            # on_son(nom_fr, label_yamnet, score)
        self.seuil = seuil
        self._classer = classer         # classer(audio) -> [(label, score)] ; None = YAMNet réel
        self._dernier: dict[str, float] = {}
        self._halt = False

    def traiter(self, resultats: "list[tuple[str, float]]") -> "tuple[str, str, float] | None":
        """Analyse une liste (label, score). Déclenche on_son sur un son surveillé. Testable."""
        for label, score in sorted(resultats, key=lambda x: x[1], reverse=True):
            if score < self.seuil:
                break
            fr = _reconnaitre(label)
            if fr is None:
                continue
            maintenant = time.monotonic()
            if maintenant - self._dernier.get(fr, 0.0) < COOLDOWN_S:
                return None
            self._dernier[fr] = maintenant
            try:
                self.on_son(fr, label, score)
            except Exception:
                log.exception("alerte sonore")
            return (fr, label, score)
        return None

    # --- Micro + YAMNet (optionnels) --------------------------------------------

    def _charger_yamnet(self):
        import tensorflow_hub as hub   # import paresseux : TensorFlow seulement si utilisé
        modele = hub.load("https://tfhub.dev/google/yamnet/1")
        import csv
        import io

        import tensorflow as tf
        chemin = tf.keras.utils.get_file("yamnet_labels.csv",
            "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv")
        with open(chemin) as f:
            etiquettes = [ligne["display_name"] for ligne in csv.DictReader(f)]

        def classer(audio):
            scores, _, _ = modele(audio)
            moyennes = scores.numpy().mean(axis=0)
            top = moyennes.argsort()[-5:][::-1]
            return [(etiquettes[i], float(moyennes[i])) for i in top]
        return classer

    def demarrer(self) -> dict:
        if self._classer is None:
            try:
                self._classer = self._charger_yamnet()
            except ImportError:
                return {"statut": "erreur",
                        "message": "L'ouïe a besoin de TensorFlow : pip install tensorflow tensorflow-hub"}
            except Exception as exc:
                return {"statut": "erreur", "message": f"YAMNet indisponible : {exc}"}
        import threading
        threading.Thread(target=self._boucle, name="jarvis-oreille", daemon=True).start()
        log.info("👂 Ouïe active (YAMNet)")
        return {"statut": "succès", "message": "J'écoute les sons de la maison."}

    def _boucle(self) -> None:
        import numpy as np
        import sounddevice as sd
        while not self._halt:
            audio = sd.rec(int(0.975 * 16000), samplerate=16000, channels=1, dtype="float32")
            sd.wait()
            try:
                self.traiter(self._classer(np.squeeze(audio)))
            except Exception:
                log.exception("boucle d'écoute")

    def arreter(self) -> None:
        self._halt = True


# --- Ouïe TinyML au bord (ESP32 + Edge Impulse) : l'événement arrive, pas l'audio ------
#
# Un ESP32 fait tourner un petit modèle entraîné sur des bruits d'effraction (verre brisé,
# coup dans une porte, aboiement de détresse). La DÉTECTION se fait SUR LA PUCE ; seul le
# RÉSULTAT (le label + un score) est publié sur MQTT. L'audio de la maison ne sort jamais.
# Jarvis réutilise toute la logique de SoundWatcher (seuil, anti-répétition, réaction).


def parse_evenement(charge: bytes) -> list:
    """Normalise un message d'inférence Edge Impulse en [(label, score)]. Souple sur le format."""
    try:
        d = json.loads(charge.decode("utf-8", "ignore"))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return []
    if not isinstance(d, dict):
        return []
    label = d.get("label") or d.get("event") or d.get("class")
    if label is not None:
        brut = d.get("value", d.get("score", d.get("confidence", 1.0)))
        try:
            return [(str(label), float(brut))]
        except (TypeError, ValueError):
            return [(str(label), 1.0)]
    cls = d.get("classification") or d.get("results") or d.get("predictions")
    source = cls if isinstance(cls, dict) else d
    out = []
    for k, v in source.items():
        if isinstance(v, (int, float)):
            out.append((str(k), float(v)))
    return out


class AcousticMqttWatcher:
    """Écoute les événements acoustiques d'un ESP32 (Edge Impulse) sur MQTT."""

    def __init__(self, sound: "SoundWatcher", host: str = "localhost", port: int = 1883,
                 topic: str = "jarvis/oreille/#", username: str = "", password: str = "", client=None):
        self.sound = sound
        self.host, self.port, self.topic = host, port, topic
        self.username, self.password = username, password
        self._client = client

    def traiter(self, charge: bytes) -> None:
        resultats = parse_evenement(charge)
        if resultats:
            try:
                self.sound.traiter(resultats)
            except Exception:
                log.exception("événement acoustique")

    def demarrer(self) -> dict:
        if self._client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                return {"statut": "erreur", "message": "paho-mqtt manquant (pip install paho-mqtt)"}
            self._client = mqtt.Client()
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_message = lambda c, u, msg: self.traiter(msg.payload)
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.subscribe(self.topic)
        except OSError as exc:
            return {"statut": "erreur", "message": f"MQTT injoignable : {exc}"}
        threading.Thread(target=self._client.loop_forever, name="jarvis-oreille-mqtt", daemon=True).start()
        log.info("👂 Ouïe TinyML à l'écoute (%s)", self.topic)
        return {"statut": "succès", "message": "À l'écoute des capteurs sonores (ESP32)"}


def make_acoustic_watcher(on_son: "Callable[[str, str, float], None]") -> "AcousticMqttWatcher | None":
    import config

    if not config.OREILLE_MQTT:
        return None
    sound = SoundWatcher(on_son, seuil=config.OREILLE_SEUIL)
    return AcousticMqttWatcher(sound, host=config.MQTT_HOST, port=config.MQTT_PORT,
                               topic=config.OREILLE_TOPIC, username=config.MQTT_USER,
                               password=config.MQTT_PASS)
