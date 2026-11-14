"""Tests de l'annonce d'arrivée (MQTT Frigate/Double Take)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import persona  # noqa: E402
from arrivals import ArrivalWatcher, _analyser, texte_arrivee  # noqa: E402


def _charge(d):
    return json.dumps(d).encode("utf-8")


# --- Lecture du message MQTT ---

def test_analyse_un_visage_connu():
    nom, camera, connu = _analyser(_charge({"name": "carlos", "camera": "entree"}))
    assert nom == "carlos" and camera == "entree" and connu


def test_analyse_un_inconnu():
    nom, camera, connu = _analyser(_charge({"name": "unknown", "camera": "garage"}))
    assert nom is None and not connu
    nom2, _, connu2 = _analyser(_charge({"camera": "garage"}))   # pas de nom du tout
    assert nom2 is None and not connu2


def test_analyse_match_faible_est_inconnu():
    nom, _, connu = _analyser(_charge({"name": "carlos", "camera": "x", "match": False}))
    assert not connu and nom is None


def test_analyse_message_invalide():
    assert _analyser(b"pas du json") is None
    assert _analyser(b"[1,2,3]") is None


# --- Formulation de l'annonce (ton de Jarvis) ---

def test_annonce_connu(monkeypatch):
    monkeypatch.setattr(config, "TITLE", "Monsieur")
    t = texte_arrivee("carlos", "entree", True)
    assert "Monsieur" in t and "Carlos" in t and "porte d'entrée" in t
    assert "caméra a détecté" not in t.lower()


def test_annonce_inconnu(monkeypatch):
    monkeypatch.setattr(config, "TITLE", "Monsieur")
    t = texte_arrivee(None, "garage", False)
    assert "non identifié" in t and "garage" in t and "éclairage de sécurité" in t


# --- Le watcher déclenche le callback, avec anti-répétition ---

def test_watcher_declenche_et_dedoublonne():
    vus = []
    w = ArrivalWatcher(lambda nom, cam, connu: vus.append((nom, cam, connu)))
    w.traiter(_charge({"name": "carlos", "camera": "entree"}))
    w.traiter(_charge({"name": "carlos", "camera": "entree"}))   # 2e message immédiat : ignoré
    assert vus == [("carlos", "entree", True)]


def test_watcher_ignore_message_invalide():
    vus = []
    w = ArrivalWatcher(lambda *a: vus.append(a))
    w.traiter(b"n'importe quoi")
    assert vus == []
