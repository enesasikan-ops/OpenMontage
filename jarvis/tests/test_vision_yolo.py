"""Tests de la détection d'objets personnalisée (YOLO) — logique sans le modèle."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from vision_yolo import YoloDetector, build_yolo_tools  # noqa: E402


def _det(resultats, seuil=0.4):
    return YoloDetector("modele.pt", seuil=seuil, predire=lambda img: resultats)


def test_filtre_par_seuil():
    d = _det([("colis", 0.91), ("personne", 0.85), ("chat", 0.2)])
    objets = dict(d.detecter(b"img"))
    assert "colis" in objets and "personne" in objets and "chat" not in objets


def test_garde_la_meilleure_confiance_par_objet():
    d = _det([("colis", 0.6), ("colis", 0.92)])
    assert dict(d.detecter(b"img"))["colis"] == 0.92


def test_tri_par_confiance():
    d = _det([("personne", 0.7), ("colis", 0.95)])
    assert [l for l, _ in d.detecter(b"img")] == ["colis", "personne"]


def test_resume():
    assert "colis" in YoloDetector.resume([("colis", 0.9)])
    assert "rien" in YoloDetector.resume([])


# --- L'outil n'existe que si un modèle est configuré ---

def test_pas_d_outil_sans_modele(monkeypatch):
    monkeypatch.setattr(config, "YOLO_MODEL", "")
    assert build_yolo_tools(NS()) == []


def test_outil_avec_modele(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "YOLO_MODEL", "modele.pt")
    cameras = NS(_is_url=lambda t: False,
                 book=NS(find=lambda n: "rtsp://x" if n == "entree" else None,
                         names=lambda: ["entree"]))
    tools = build_yolo_tools(cameras)
    assert len(tools) == 1 and tools[0].name == "detecter_objets"
    # caméra inconnue -> message clair, pas de plantage
    assert "entree" in tools[0].run("grenier")
