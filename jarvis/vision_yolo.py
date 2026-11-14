"""Détection d'objets personnalisée (Ultralytics YOLO), en local.

Tu entraînes YOLO sur tes propres objets (colis, porte de garage ouverte, outil manquant…)
et Jarvis les reconnaît sur les caméras : « Colis détecté devant la porte » au lieu d'un
vague « personne détectée ».

La logique (seuil, dédoublonnage, résumé) est séparée du modèle, donc testable sans YOLO.
Le modèle (ultralytics) est en import paresseux.
"""

from __future__ import annotations

import logging
from typing import Callable

import config

log = logging.getLogger(__name__)


class YoloDetector:
    def __init__(self, model_path: str, seuil: float = 0.4, predire: "Callable | None" = None):
        self.model_path = model_path
        self.seuil = seuil
        self._predire = predire     # predire(image_bytes) -> [(label, conf)] ; None = YOLO réel
        self._model = None

    def _charger(self):
        from ultralytics import YOLO   # import paresseux
        return YOLO(self.model_path)

    def _inference(self, image: bytes) -> "list[tuple[str, float]]":
        import cv2
        import numpy as np
        if self._model is None:
            self._model = self._charger()
        img = cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return []
        r = self._model(img, verbose=False)[0]
        noms = self._model.names
        return [(str(noms[int(b.cls)]), float(b.conf)) for b in r.boxes]

    def detecter(self, image: bytes) -> "list[tuple[str, float]]":
        """Renvoie les objets détectés [(label, confiance)], filtrés et dédoublonnés."""
        brut = self._predire(image) if self._predire is not None else self._inference(image)
        garde: dict[str, float] = {}
        for label, conf in brut:
            if conf >= self.seuil and conf > garde.get(label, 0.0):
                garde[label] = conf     # on garde la meilleure confiance par type d'objet
        return sorted(garde.items(), key=lambda x: x[1], reverse=True)

    @staticmethod
    def resume(detections: "list[tuple[str, float]]") -> str:
        if not detections:
            return "Je ne vois rien de particulier."
        return "Je vois : " + ", ".join(f"{label}" for label, _ in detections) + "."


def build_yolo_tools(cameras) -> list:
    if not config.YOLO_MODEL:
        return []
    from camera import grab_frame
    from tools import Tool

    detector = YoloDetector(config.YOLO_MODEL, config.YOLO_SEUIL)

    def detecter_sur(camera: str) -> str:
        url = camera if cameras._is_url(camera) else cameras.book.find(camera)
        if not url:
            dispo = ", ".join(cameras.book.names()) or "aucune"
            return f"Je ne connais pas la caméra « {camera} ». Caméras : {dispo}."
        image = grab_frame(url)
        if not image:
            return "Je n'arrive pas à capturer l'image de cette caméra."
        return detector.resume(detector.detecter(image))

    return [Tool(
        name="detecter_objets",
        description=("Analyse une caméra avec le modèle personnalisé pour reconnaître des objets "
                     "précis (colis, porte de garage ouverte, outil…). « Y a-t-il un colis à l'entrée ? »"),
        parameters={"type": "object",
                    "properties": {"camera": {"type": "string", "description": "nom de la caméra"}},
                    "required": ["camera"]},
        run=detecter_sur,
    )]
