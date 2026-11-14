"""Tests du fil d'alarme OPNsense (tentative IoT -> cœur = objet compromis)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from opnsense import (OpnsenseWatcher, build_opnsense_tools, dans_reseau,  # noqa: E402
                      franchissements, make_opnsense_watcher, message)

COEUR = ("10.0.1.0/24",)
IOT = ("10.0.9.0/24",)


def _ev(src, dst, action="block", dstport=22, ts="t1"):
    return {"__timestamp__": ts, "action": action, "src": src, "dst": dst, "dstport": dstport}


# --- Appartenance réseau ---

def test_dans_reseau():
    assert dans_reseau("10.0.9.50", IOT) is True
    assert dans_reseau("10.0.1.5", IOT) is False
    assert dans_reseau("pas une ip", IOT) is False


# --- Détection de franchissement ---

def test_franchissement_iot_vers_coeur():
    evs = [_ev("10.0.9.50", "10.0.1.5")]            # ampoule IoT -> serveur cœur, bloqué
    assert len(franchissements(evs, COEUR, IOT)) == 1


def test_coeur_vers_iot_autorise_ignore():
    evs = [_ev("10.0.1.5", "10.0.9.50", action="pass")]   # Jarvis pilote l'IoT : normal
    assert franchissements(evs, COEUR, IOT) == []


def test_trafic_interne_iot_ignore():
    evs = [_ev("10.0.9.50", "10.0.9.51")]           # IoT -> IoT : pas un franchissement
    assert franchissements(evs, COEUR, IOT) == []


def test_bloque_mais_pas_vers_coeur_ignore():
    evs = [_ev("10.0.9.50", "8.8.8.8")]             # IoT -> Internet bloqué : hors sujet ici
    assert franchissements(evs, COEUR, IOT) == []


def test_message_nomme_la_source():
    m = message(_ev("10.0.9.50", "10.0.1.5"))
    assert "10.0.9.50" in m and "10.0.1.5" in m and "compromis" in m


# --- Watcher ---

def test_watcher_apprend_puis_alerte():
    seq = [[], [_ev("10.0.9.50", "10.0.1.5", ts="t2")]]
    i = {"n": 0}

    def fetch():
        d = seq[min(i["n"], len(seq) - 1)]
        i["n"] += 1
        return d

    notifs = []
    w = OpnsenseWatcher(fetch, notifs.append, COEUR, IOT)
    assert w.un_tour() == []                 # 1er passage : apprentissage
    w.un_tour()
    assert any("tenté d'atteindre le cœur" in n for n in notifs)


def test_watcher_pas_de_repetition():
    ev = _ev("10.0.9.50", "10.0.1.5", ts="t3")
    w = OpnsenseWatcher(lambda: [ev], notify=lambda m: None, coeur=COEUR, iot=IOT)
    w.un_tour()                              # apprend l'événement existant
    assert w.un_tour() == []                 # même événement : silencieux


def test_watcher_opnsense_injoignable():
    def boom():
        raise OSError("api down")
    assert OpnsenseWatcher(boom, lambda m: None, COEUR, IOT).un_tour() == []


# --- Outil / fabrique ---

def _config(monkeypatch):
    monkeypatch.setattr(config, "OPNSENSE", True)
    monkeypatch.setattr(config, "OPNSENSE_KEY", "cle")
    monkeypatch.setattr(config, "OPNSENSE_COEUR", COEUR)
    monkeypatch.setattr(config, "OPNSENSE_IOT", IOT)


def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "OPNSENSE", False)
    assert build_opnsense_tools(fetch=lambda: []) == []


def test_outil_signale_tentative(monkeypatch):
    _config(monkeypatch)
    tools = {t.name: t for t in build_opnsense_tools(fetch=lambda: [_ev("10.0.9.50", "10.0.1.5")])}
    assert "franchissement" in tools["point_pare_feu"].run()


def test_outil_cage_tient(monkeypatch):
    _config(monkeypatch)
    tools = {t.name: t for t in build_opnsense_tools(fetch=lambda: [])}
    assert "cage tient" in tools["point_pare_feu"].run()


def test_make_watcher_desactive(monkeypatch):
    monkeypatch.setattr(config, "OPNSENSE", False)
    assert make_opnsense_watcher(lambda m: None) is None
