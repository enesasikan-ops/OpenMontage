"""Caméras par adresse de flux, pour Jarvis.

Tu donnes l'adresse d'un flux vidéo (une caméra PUBLIQUE officielle — trafic, plage,
nature — ou une caméra à toi). Jarvis prend une image et te décrit ce qu'il voit.
Tu peux enregistrer des caméras par un nom (« la plage de Nice ») et les rappeler.

À n'utiliser que pour des caméras **ouvertes au public** ou **qui t'appartiennent**.
Jamais pour accéder à la caméra privée de quelqu'un d'autre.
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Callable


GRAB_TIMEOUT_S = 25


def _clip_cmd(url: str, path: str, seconds: int) -> list[str]:
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-protocol_whitelist", "rtsp,rtp,tcp,udp,https,tls,http"]   # jamais file:// (anti lecture disque)
    if url.lower().startswith("rtsp://"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url, "-t", str(seconds), "-c", "copy", "-movflags", "+faststart", path]
    return cmd


def grab_clip(url: str, seconds: int = 8, run: Callable = subprocess.run) -> "str | None":
    """Enregistre un court clip (mp4) d'un flux caméra. Renvoie le chemin, ou None."""
    import os
    import tempfile
    if not url.lower().startswith(("rtsp://", "http://", "https://")):
        return None
    path = tempfile.mkstemp(suffix=".mp4")[1]
    try:
        run(_clip_cmd(url, path, seconds), capture_output=True, timeout=seconds + 20)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return path if os.path.getsize(path) > 0 else None
    except OSError:
        return None


def grab_frame(url: str, run: Callable = subprocess.run, timeout: int = GRAB_TIMEOUT_S) -> "bytes | None":
    """Capture une seule image du flux (via ffmpeg). Renvoie un JPEG, ou None."""
    # Seules les caméras réseau sont permises : pas de file:// (lecture de fichiers locaux).
    if not url.lower().startswith(("rtsp://", "http://", "https://")):
        return None
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           # Liste blanche de protocoles : ffmpeg ne touchera jamais au disque (pas de "file").
           "-protocol_whitelist", "rtsp,rtp,tcp,udp,https,tls,http"]
    if url.lower().startswith("rtsp://"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd += ["-i", url, "-frames:v", "1", "-f", "image2", "-vcodec", "mjpeg", "pipe:1"]
    try:
        out = run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    data = getattr(out, "stdout", None)
    return data if data else None


class CameraBook:
    """Caméras enregistrées : nom -> adresse de flux. Fichier local."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, name: str, url: str) -> None:
        self.data[name.strip().lower()] = url.strip()
        self.save()

    def find(self, name: str) -> "str | None":
        return self.data.get(name.strip().lower())

    def remove(self, name: str) -> bool:
        key = name.strip().lower()
        if key in self.data:
            del self.data[key]
            self.save()
            return True
        return False

    def names(self) -> list[str]:
        return sorted(self.data)


class CameraManager:
    def __init__(self, book: CameraBook, describe: "Callable[[bytes, str], str] | None" = None,
                 grab: Callable = grab_frame):
        self.book = book
        self.describe = describe
        self.grab = grab

    @staticmethod
    def _is_url(text: str) -> bool:
        return text.strip().lower().startswith(("http://", "https://", "rtsp://", "rtmp://"))

    def add(self, nom: str, adresse: str) -> str:
        if not self._is_url(adresse):
            return "L'adresse doit être un lien de flux (http://, https:// ou rtsp://)."
        self.book.add(nom, adresse)
        return f"C'est noté : la caméra « {nom} » est enregistrée."

    def forget(self, nom: str) -> str:
        return (f"J'ai oublié la caméra « {nom} »." if self.book.remove(nom)
                else f"Je n'ai pas de caméra « {nom} ».")

    def list_text(self) -> str:
        names = self.book.names()
        return "Caméras enregistrées : " + ", ".join(names) + "." if names else "Aucune caméra enregistrée."

    def look(self, camera: str) -> str:
        url = camera if self._is_url(camera) else self.book.find(camera)
        if not url:
            dispo = ", ".join(self.book.names()) or "aucune"
            return f"Je ne connais pas la caméra « {camera} ». Enregistrées : {dispo}."
        frame = self.grab(url)
        if not frame:
            return "Je n'arrive pas à récupérer l'image de cette caméra (adresse ou flux indisponible)."
        if self.describe is None:
            return ("J'ai bien l'image de la caméra, mais la vision n'est pas configurée pour la décrire "
                    "(voir JARVIS_MODELE_VISION).")
        question = "Décris ce que montre cette caméra, en une ou deux phrases, en français."
        try:
            return self.describe(frame, question)
        except Exception:
            return "Je n'arrive pas à analyser l'image de la caméra."


def build_camera_tools(manager: CameraManager) -> list:
    from tools import Tool

    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [
        Tool(name="regarder_camera",
             description=("Regarde une caméra (publique ou à toi) et décrit ce qu'elle montre. "
                          "Donne un nom enregistré (« la plage ») ou une adresse de flux directe."),
             parameters=obj({"camera": {**s, "description": "Nom enregistré ou adresse du flux."}}, ["camera"]),
             run=manager.look),
        Tool(name="ajouter_camera",
             description="Enregistre une caméra publique (ou à toi) sous un nom, par son adresse de flux.",
             parameters=obj({"nom": {**s, "description": "Un nom court, ex. « plage de Nice »."},
                             "adresse": {**s, "description": "L'adresse du flux (http://, https:// ou rtsp://)."}},
                            ["nom", "adresse"]),
             run=manager.add),
        Tool(name="lister_cameras",
             description="Liste les caméras enregistrées.",
             parameters=obj({}, []),
             run=lambda: manager.list_text()),
        Tool(name="oublier_camera",
             description="Oublie une caméra enregistrée.",
             parameters=obj({"nom": {**s, "description": "Le nom de la caméra à oublier."}}, ["nom"]),
             run=manager.forget),
    ] + _ptz_tools(manager) + _yolo_tools(manager)


def _yolo_tools(manager: CameraManager) -> list:
    """Détection d'objets personnalisée (YOLO), si un modèle est configuré."""
    try:
        from vision_yolo import build_yolo_tools
        return build_yolo_tools(manager)
    except Exception:
        logging.getLogger(__name__).exception("chargement des outils YOLO")
        return []


def _ptz_tools(manager: CameraManager) -> list:
    """Outils de caméra motorisée (PTZ) + ronde, si des caméras PTZ sont configurées."""
    try:
        from ptz import build_ptz_tools
        return build_ptz_tools(look=manager.look)   # look = orienter puis décrire la vue
    except Exception:  # un souci PTZ ne doit pas priver Jarvis des autres outils caméra
        logging.getLogger(__name__).exception("chargement des outils PTZ")
        return []
