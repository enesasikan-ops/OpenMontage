"""Tests de l'ouïe analytique (classification des sons)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hearing import SoundWatcher, _reconnaitre  # noqa: E402


def test_reconnaissance_des_sons():
    assert _reconnaitre("Glass") == "bris de glace"
    assert _reconnaitre("Shatter") == "bris de glace"
    assert _reconnaitre("Smoke detector, smoke alarm") == "alarme incendie"
    assert _reconnaitre("Gunshot, gunfire") == "coup de feu"
    assert _reconnaitre("Speech") is None            # parole : pas un son surveillé
    assert _reconnaitre("Music") is None


def test_alerte_sur_son_surveille():
    vus = []
    w = SoundWatcher(lambda fr, label, score: vus.append((fr, round(score, 2))))
    out = w.traiter([("Speech", 0.6), ("Glass", 0.82), ("Music", 0.3)])
    assert out[0] == "bris de glace"
    assert vus == [("bris de glace", 0.82)]


def test_sous_le_seuil_rien():
    vus = []
    w = SoundWatcher(lambda *a: vus.append(a), seuil=0.5)
    assert w.traiter([("Glass", 0.3)]) is None       # trop faible
    assert vus == []


def test_son_non_surveille_ignore():
    vus = []
    w = SoundWatcher(lambda *a: vus.append(a))
    assert w.traiter([("Dishes", 0.9), ("Typing", 0.8)]) is None
    assert vus == []


def test_pas_deux_alertes_rapprochees():
    vus = []
    w = SoundWatcher(lambda *a: vus.append(a))
    w.traiter([("Glass", 0.9)])
    w.traiter([("Glass", 0.9)])      # juste après : ignoré (anti-répétition)
    assert len(vus) == 1


# --- Ouïe TinyML au bord (ESP32 / Edge Impulse via MQTT) ---

import json as _json  # noqa: E402

from hearing import (AcousticMqttWatcher, SoundWatcher,  # noqa: E402
                     make_acoustic_watcher, parse_evenement)


def test_parse_forme_label_valeur():
    assert parse_evenement(_json.dumps({"label": "glass_break", "value": 0.92}).encode()) == [("glass_break", 0.92)]


def test_parse_forme_classification():
    res = dict(parse_evenement(_json.dumps({"classification": {"door_kick": 0.8, "noise": 0.1}}).encode()))
    assert res["door_kick"] == 0.8 and res["noise"] == 0.1


def test_parse_forme_plate():
    res = dict(parse_evenement(_json.dumps({"bark": 0.7, "silence": 0.2}).encode()))
    assert res["bark"] == 0.7


def test_parse_json_invalide():
    assert parse_evenement(b"pas du json") == []


def test_watcher_mqtt_declenche_sur_son():
    recu = []
    sound = SoundWatcher(lambda fr, label, score: recu.append((fr, score)), seuil=0.5)
    w = AcousticMqttWatcher(sound)
    w.traiter(_json.dumps({"label": "glass_break", "value": 0.95}).encode())
    assert recu and recu[0][0] == "bris de glace"      # mappé en français via SONS


def test_watcher_mqtt_ignore_bruit_de_fond():
    recu = []
    sound = SoundWatcher(lambda fr, label, score: recu.append(fr), seuil=0.5)
    AcousticMqttWatcher(sound).traiter(_json.dumps({"label": "noise", "value": 0.99}).encode())
    assert recu == []                                   # 'noise' n'est pas un son surveillé


def test_coup_dans_la_porte_reconnu():
    recu = []
    sound = SoundWatcher(lambda fr, label, score: recu.append(fr), seuil=0.5)
    AcousticMqttWatcher(sound).traiter(_json.dumps({"label": "door_kick", "value": 0.8}).encode())
    assert recu == ["coup dans une porte"]


def test_make_desactive(monkeypatch):
    import config
    monkeypatch.setattr(config, "OREILLE_MQTT", False)
    assert make_acoustic_watcher(lambda *a: None) is None
