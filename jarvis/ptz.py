"""Pilotage des caméras motorisées (PTZ : pan-tilt-zoom), via ONVIF.

« Jarvis, regarde vers le portail », « tourne la caméra du jardin à gauche ».
Standard ONVIF : marche avec Reolink et la plupart des caméras motorisées.

Les caméras PTZ et leurs accès sont dans un fichier JSON (config.PTZ_FILE) :
  { "jardin": {"host": "192.168.1.50", "port": 80, "user": "admin", "pass": "..."} }
(le mot de passe reste en local, jamais dans git.)
"""

from __future__ import annotations

import logging
import time
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


def _aller_preset_onvif(infos: dict, token: str) -> None:
    """Va à une position mémorisée (preset) via ONVIF GotoPreset."""
    from onvif import ONVIFCamera

    cam = ONVIFCamera(infos["host"], int(infos.get("port", 80)),
                      infos.get("user", ""), infos.get("pass", ""))
    ptz = cam.create_ptz_service()
    media = cam.create_media_service()
    profil = media.GetProfiles()[0].token
    ptz.GotoPreset({"ProfileToken": profil, "PresetToken": str(token)})


class PtzController:
    def __init__(self, book: JsonStore, mover: Callable = _bouger_onvif,
                 preset_mover: Callable = _aller_preset_onvif):
        self.book = book
        self.mover = mover
        self.preset_mover = preset_mover

    def cameras(self) -> list[str]:
        return sorted(self.book.data.keys())

    def presets(self, camera: str) -> dict:
        """Positions mémorisées d'une caméra : { nom: token }."""
        infos = self.book.data.get((camera or "").strip().lower())
        return dict((infos or {}).get("presets", {}))

    def aller_preset(self, camera: str, token: str) -> None:
        infos = self.book.data.get((camera or "").strip().lower())
        if infos is not None:
            self.preset_mover(infos, token)

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


class PatrolController:
    """La ronde : Jarvis passe la caméra sur chaque position mémorisée et décrit ce qu'il voit."""

    def __init__(self, ptz: PtzController, look: Callable, settle_s: float = 2.0):
        self.ptz = ptz
        self.look = look          # look(camera) -> description de ce que montre la caméra
        self.settle_s = settle_s  # temps de stabilisation après un déplacement

    def tour(self, camera: str) -> str:
        presets = self.ptz.presets(camera)
        if not presets:
            return (f"La caméra « {camera} » n'a pas de positions mémorisées. "
                    "Définis-en dans l'appli (portail, allée…) puis ajoute-les à sa config.")
        lignes = []
        for nom, token in presets.items():
            try:
                self.ptz.aller_preset(camera, token)
            except Exception:
                log.exception("ronde : position %s", nom)
                continue
            time.sleep(self.settle_s)
            try:
                desc = self.look(camera)
            except Exception:
                desc = "vue indisponible"
            lignes.append(f"{nom}, {desc}")
        if not lignes:
            return f"Je n'ai pas pu faire le tour de « {camera} »."
        return "Ronde terminée. " + " ".join(f"{l}." for l in lignes)


def build_ptz_tools(book: "JsonStore | None" = None, look: "Callable | None" = None) -> list:
    """Outils de caméra motorisée, seulement si des caméras PTZ sont configurées.
    `look(camera) -> str` (facultatif) active la ronde (« fais le tour »)."""
    book = book or JsonStore(config.PTZ_FILE, {})
    if not book.data:
        return []
    ptz = PtzController(book)

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    outils = [Tool(
        name="tourner_camera",
        description="Oriente une caméra motorisée (PTZ). Direction : gauche, droite, haut, bas.",
        parameters=obj({
            "camera": {"type": "string", "description": "nom de la caméra (ex. jardin, portail)"},
            "direction": {"type": "string", "enum": ["gauche", "droite", "haut", "bas"]},
            "duree": {"type": "number", "description": "secondes (défaut 1, max 5)"},
        }, ["camera", "direction"]),
        run=lambda camera, direction, duree=1.0: ptz.tourner(camera, direction, duree),
    )]

    # La ronde : disponible si on sait décrire la vue, et si au moins une caméra a des positions.
    if look is not None and any(ptz.presets(c) for c in ptz.cameras()):
        patrol = PatrolController(ptz, look)
        outils.append(Tool(
            name="faire_le_tour",
            description=("Fais une ronde avec une caméra motorisée : passe sur chaque position "
                         "mémorisée et décris ce que tu vois (« fais le tour du jardin »)."),
            parameters=obj({"camera": {"type": "string", "description": "nom de la caméra"}}, ["camera"]),
            run=lambda camera: patrol.tour(camera),
        ))
    return outils
