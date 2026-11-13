"""Pilotage des caméras motorisées (PTZ : pan-tilt-zoom), via ONVIF.

« Jarvis, regarde vers le portail », « tourne la caméra du jardin à gauche ».
Standard ONVIF : marche avec Reolink et la plupart des caméras motorisées.

Les caméras PTZ et leurs accès sont dans un fichier JSON (config.PTZ_FILE) :
  { "jardin": {"host": "192.168.1.50", "port": 80, "user": "admin", "pass": "..."} }
(le mot de passe reste en local, jamais dans git.)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import config
from skills import JsonStore
from tools import Tool

log = logging.getLogger(__name__)

# direction -> (pan, tilt) : vitesses ONVIF entre -1 et 1.
VITESSE = 0.5
_DIRECTIONS = {
    "gauche": (-VITESSE, 0.0), "droite": (VITESSE, 0.0),
    "haut": (0.0, VITESSE), "bas": (0.0, -VITESSE),
}
DUREE_MAX = 5.0


def _bouger_onvif(infos: dict, pan: float, tilt: float, duree: float) -> None:
    """Déplacement réel via ONVIF : ContinuousMove pendant `duree`, puis Stop."""
    import time

    from onvif import ONVIFCamera  # import paresseux : onvif-zeep seulement si utilisé

    cam = ONVIFCamera(infos["host"], int(infos.get("port", 80)),
                      infos.get("user", ""), infos.get("pass", ""))
    ptz = cam.create_ptz_service()
    media = cam.create_media_service()
    token = media.GetProfiles()[0].token
    requete = ptz.create_type("ContinuousMove")
    requete.ProfileToken = token
    requete.Velocity = {"PanTilt": {"x": pan, "y": tilt}}
    ptz.ContinuousMove(requete)
    time.sleep(duree)
    ptz.Stop({"ProfileToken": token})


class PtzController:
    def __init__(self, book: JsonStore, mover: Callable = _bouger_onvif):
        self.book = book
        self.mover = mover

    def cameras(self) -> list[str]:
        return sorted(self.book.data.keys())

    def tourner(self, camera: str, direction: str, duree: float = 1.0) -> str:
        camera = (camera or "").strip().lower()
        direction = (direction or "").strip().lower()
        infos = self.book.data.get(camera)
        if infos is None:
            dispo = ", ".join(self.cameras()) or "aucune"
            return f"Je ne connais pas la caméra motorisée « {camera} ». Disponibles : {dispo}."
        if direction not in _DIRECTIONS:
            return "Direction inconnue. Dis : gauche, droite, haut ou bas."
        duree = max(0.1, min(float(duree), DUREE_MAX))   # jamais plus de 5 s d'un coup
        pan, tilt = _DIRECTIONS[direction]
        try:
            self.mover(infos, pan, tilt, duree)
        except ImportError:
            return "Le pilotage PTZ a besoin de la bibliothèque onvif-zeep (pip install onvif-zeep)."
        except Exception as exc:
            log.error("PTZ %s : %s", camera, exc)
            return f"Je n'arrive pas à bouger la caméra « {camera} »."
        return f"C'est fait, j'ai tourné la caméra « {camera} » vers la {direction}." \
            if direction in ("gauche", "droite") else \
            f"C'est fait, j'ai incliné la caméra « {camera} » vers le {direction}."


def build_ptz_tools(book: "JsonStore | None" = None) -> list:
    """Outil « tourner_camera », seulement si des caméras motorisées sont configurées."""
    book = book or JsonStore(config.PTZ_FILE, {})
    if not book.data:
        return []
    ptz = PtzController(book)

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [Tool(
        name="tourner_camera",
        description="Oriente une caméra motorisée (PTZ). Direction : gauche, droite, haut, bas.",
        parameters=obj({
            "camera": {"type": "string", "description": "nom de la caméra (ex. jardin, portail)"},
            "direction": {"type": "string", "enum": ["gauche", "droite", "haut", "bas"]},
            "duree": {"type": "number", "description": "secondes (défaut 1, max 5)"},
        }, ["camera", "direction"]),
        run=lambda camera, direction, duree=1.0: ptz.tourner(camera, direction, duree),
    )]
