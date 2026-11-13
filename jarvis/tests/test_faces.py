"""Tests de la reconnaissance de visages, avec un faux moteur (aucune vraie photo)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faces import FaceStore, Recognizer, build_face_tools  # noqa: E402


class FakeEngine:
    """Associe un contenu d'image à des signatures connues, pour tester la logique."""

    FACES = {
        b"enes": [[0.0] * 128],
        b"cousine": [[1.0] * 128],
        b"enes-et-inconnu": [[0.01] * 128, [5.0] * 128],
        b"inconnu": [[9.0] * 128],
        b"flou": [],
        b"deux": [[0.0] * 128, [1.0] * 128],
    }

    def embeddings(self, image: bytes):
        return self.FACES.get(image, [])


def reco(tmp_path):
    return Recognizer(FakeEngine(), FaceStore(tmp_path / "visages.json"))


def test_enroll_then_recognize(tmp_path):
    r = reco(tmp_path)
    assert "Je ne connais encore personne" in r.identify(b"enes")
    assert "Enes" in r.enroll("Enes", b"enes")
    assert r.identify(b"enes") == "Je reconnais Enes."


def test_unknown_person(tmp_path):
    r = reco(tmp_path)
    r.enroll("Enes", b"enes")
    assert "ne reconnais personne" in r.identify(b"inconnu")


def test_several_people(tmp_path):
    r = reco(tmp_path)
    r.enroll("Enes", b"enes")
    r.enroll("Cousine", b"cousine")
    assert r.identify(b"deux") == "Je reconnais Enes et Cousine."


def test_known_and_unknown_mix(tmp_path):
    r = reco(tmp_path)
    r.enroll("Enes", b"enes")
    out = r.identify(b"enes-et-inconnu")
    assert "Je reconnais Enes" in out and "que je ne connais pas" in out


def test_enroll_rejects_no_face_or_many(tmp_path):
    r = reco(tmp_path)
    assert "pas de visage" in r.enroll("X", b"flou")
    assert "plusieurs visages" in r.enroll("X", b"deux")
    assert "un nom" in r.enroll("", b"enes")


def test_no_face_in_view(tmp_path):
    r = reco(tmp_path)
    r.enroll("Enes", b"enes")
    assert "aucun visage" in r.identify(b"flou")


def test_forget_and_list(tmp_path):
    r = reco(tmp_path)
    r.enroll("Enes", b"enes")
    r.enroll("Cousine", b"cousine")
    assert "Enes" in r.known() and "Cousine" in r.known()
    assert "oublié" in r.forget("enes")          # insensible à la casse
    assert "pas de visage" in r.forget("Inconnu")
    assert r.identify(b"enes").endswith("ne reconnais personne.") or "Cousine" not in r.identify(b"enes")


def test_persists_on_disk(tmp_path):
    reco(tmp_path).enroll("Enes", b"enes")
    # Nouveau Recognizer, même fichier : le visage est toujours connu.
    r2 = Recognizer(FakeEngine(), FaceStore(tmp_path / "visages.json"))
    assert r2.identify(b"enes") == "Je reconnais Enes."


def test_engine_error_is_friendly(tmp_path):
    class Broken(FakeEngine):
        def embeddings(self, image):
            raise RuntimeError("modèle absent")

    r = Recognizer(Broken(), FaceStore(tmp_path / "v.json"))
    assert "pas à analyser" in r.enroll("X", b"enes")
    r.store.add("Enes", [0.0] * 128)
    assert "pas à analyser" in r.identify(b"enes")


def test_tools_enroll_from_file_and_confirmation(tmp_path):
    r = reco(tmp_path)
    photo = tmp_path / "moi.jpg"
    photo.write_bytes(b"enes")
    frames = [b"enes"]
    tools = {t.name: t for t in build_face_tools(r, frame_provider=lambda: frames[0])}
    # Enregistrement : demande confirmation (donnée biométrique)
    assert "accord" in tools["enregistrer_visage"].confirm(nom="Enes", photo=str(photo))
    assert "Enes" in tools["enregistrer_visage"].run(nom="Enes", photo=str(photo))
    # Reconnaissance sur la vue courante (ex. drone)
    assert tools["qui_est_la"].run() == "Je reconnais Enes."
    # Photo introuvable
    assert "ne trouve pas" in tools["enregistrer_visage"].run(nom="X", photo="/pas/de/photo.jpg")


def test_tool_recognize_without_camera(tmp_path):
    r = reco(tmp_path)
    r.enroll("Enes", b"enes")
    tools = {t.name: t for t in build_face_tools(r, frame_provider=None)}
    assert "pas de caméra" in tools["qui_est_la"].run()
