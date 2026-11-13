"""Reconnaissance de visages pour Jarvis — en local, pour les gens que TU enregistres.

Tu donnes une photo (« voici une photo de moi ») et un nom ; Jarvis apprend le visage.
Ensuite il peut te reconnaître sur la caméra ou la vue du drone.

Vie privée et éthique :
- Tout reste sur l'ordinateur (un fichier de signatures, pas les photos).
- Ça ne sert qu'à reconnaître les personnes que TU as enregistrées, avec leur accord.
  Ce n'est pas fait pour identifier des inconnus ni pour surveiller des gens.
- Une « signature de visage » est une donnée personnelle : enregistrer quelqu'un demande
  confirmation, et tu peux l'oublier à tout moment.
"""

import json
import logging
import math
from pathlib import Path
from typing import Callable, Protocol


log = logging.getLogger("jarvis.visages")

# Seuil de ressemblance (distance entre signatures). Plus bas = plus strict.
THRESHOLD = 0.6


class FaceEngine(Protocol):
    """Transforme une image en signatures de visages (une par visage détecté)."""

    def embeddings(self, image: bytes) -> list[list[float]]: ...


class FaceRecognitionEngine:
    """Moteur local par défaut, via la bibliothèque `face_recognition` (chargée à la demande)."""

    def embeddings(self, image: bytes) -> list[list[float]]:
        import io

        import face_recognition  # lourd (dlib) : installé seulement si tu actives les visages
        import numpy as np
        from PIL import Image

        img = np.array(Image.open(io.BytesIO(image)).convert("RGB"))
        locations = face_recognition.face_locations(img)
        return [list(map(float, e)) for e in face_recognition.face_encodings(img, locations)]


def _distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


class FaceStore:
    """Signatures enregistrées : nom -> liste de signatures. Fichier local."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, name: str, embedding: list[float]) -> None:
        self.data.setdefault(name, []).append(embedding)
        self.save()

    def remove(self, name: str) -> bool:
        for key in list(self.data):
            if key.lower() == name.lower():
                del self.data[key]
                self.save()
                return True
        return False

    def names(self) -> list[str]:
        return sorted(self.data)


class Recognizer:
    def __init__(self, engine: FaceEngine, store: FaceStore, threshold: float = THRESHOLD):
        self.engine = engine
        self.store = store
        self.threshold = threshold

    def enroll(self, name: str, image: bytes) -> str:
        name = name.strip()
        if not name:
            return "Il me faut un nom pour enregistrer ce visage."
        try:
            faces = self.engine.embeddings(image)
        except Exception as exc:
            log.warning("enroll : %s", exc)
            return "Je n'arrive pas à analyser cette photo."
        if not faces:
            return "Je ne vois pas de visage sur cette photo. Essaie une photo plus nette, de face."
        if len(faces) > 1:
            return "Il y a plusieurs visages sur la photo. Donne-m'en une avec un seul visage."
        self.store.add(name, faces[0])
        return f"C'est noté, je reconnaîtrai {name} maintenant."

    def _match(self, embedding: list[float]) -> "str | None":
        best_name, best_dist = None, self.threshold
        for name, known in self.store.data.items():
            for ref in known:
                d = _distance(embedding, ref)
                if d < best_dist:
                    best_name, best_dist = name, d
        return best_name

    def identify(self, image: bytes) -> str:
        if not self.store.data:
            return "Je ne connais encore personne. Donne-moi une photo pour commencer."
        try:
            faces = self.engine.embeddings(image)
        except Exception as exc:
            log.warning("identify : %s", exc)
            return "Je n'arrive pas à analyser l'image."
        if not faces:
            return "Je ne vois aucun visage."
        names = [self._match(f) for f in faces]
        known = [n for n in names if n]
        unknown = len(names) - len(known)
        if known and not unknown:
            return "Je reconnais " + _join(known) + "."
        if known and unknown:
            return ("Je reconnais " + _join(known)
                    + f", et {unknown} personne(s) que je ne connais pas.")
        return f"Je vois {len(faces)} visage(s), mais je ne reconnais personne."

    def forget(self, name: str) -> str:
        return (f"J'ai oublié le visage de {name}." if self.store.remove(name)
                else f"Je n'ai pas de visage enregistré pour {name}.")

    def known(self) -> str:
        names = self.store.names()
        return "Je connais : " + ", ".join(names) + "." if names else "Je ne connais encore aucun visage."


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " et " + items[-1]


def build_face_tools(recognizer: Recognizer, frame_provider: "Callable[[], bytes | None]" = None) -> list:
    from tools import Tool

    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    def enroll_from_file(nom: str, photo: str) -> str:
        path = Path(photo).expanduser()
        try:
            image = path.read_bytes()
        except OSError:
            return f"Je ne trouve pas la photo « {photo} »."
        return recognizer.enroll(nom, image)

    def recognize_now() -> str:
        if frame_provider is None:
            return "Je n'ai pas de caméra pour regarder en ce moment."
        frame = frame_provider()
        if not frame:
            return "Je n'ai pas d'image à regarder pour le moment."
        return recognizer.identify(frame)

    tools = [
        Tool(name="enregistrer_visage",
             description=("Apprend le visage d'une personne à partir d'une photo (fichier image), "
                          "pour la reconnaître ensuite. Pour « voici une photo de moi, retiens mon visage »."),
             parameters=obj({"nom": {**s, "description": "Le nom de la personne."},
                             "photo": {**s, "description": "Le chemin du fichier photo."}}, ["nom", "photo"]),
             run=enroll_from_file,
             confirm=lambda nom, photo: (f"Je vais enregistrer le visage de {nom} (donnée personnelle, "
                                         "gardée sur cet ordinateur). Tu as son accord ?")),
        Tool(name="oublier_visage",
             description="Oublie le visage d'une personne enregistrée.",
             parameters=obj({"nom": {**s, "description": "Le nom à oublier."}}, ["nom"]),
             run=recognizer.forget),
        Tool(name="visages_connus",
             description="Liste les personnes dont Jarvis connaît le visage.",
             parameters=obj({}, []),
             run=recognizer.known),
        Tool(name="qui_est_la",
             description=("Regarde la caméra (ou la vue du drone) et dit quelles personnes connues "
                          "sont présentes. Pour « qui est là ? », « tu me reconnais ? »."),
             parameters=obj({}, []),
             run=recognize_now),
    ]
    return tools
