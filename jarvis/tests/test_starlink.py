"""Tests de la surveillance Starlink (liaison Internet : coupure, obstruction)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from starlink import (StarlinkWatcher, analyser, build_starlink_tools,  # noqa: E402
                      etat, make_starlink_watcher, rapport)


def _getter(d):
    return lambda: d


# --- Analyse ---

def test_tout_va_bien():
    e = etat(_getter({"state": "CONNECTED", "latence_ms": 40, "obstruction": 0.0}))
    a = analyser(e)
    assert a["probleme"] is False and "Tout va bien" in rapport(e)


def test_coupure():
    a = analyser(etat(_getter({"state": "SEARCHING"})))
    assert a["probleme"] and any("interrompue" in m for m in a["messages"])


def test_obstruction():
    a = analyser(etat(_getter({"state": "CONNECTED", "obstruction": 0.08})))
    assert any("obstruée" in m and "8 %" in m for m in a["messages"])


def test_alerte_materiel():
    a = analyser(etat(_getter({"state": "CONNECTED", "alertes": ["thermal_throttle"]})))
    assert any("thermal_throttle" in m for m in a["messages"])


def test_latence_elevee():
    a = analyser(etat(_getter({"state": "CONNECTED", "latence_ms": 300})))
    assert any("Latence élevée" in m for m in a["messages"])


def test_defauts_surs():
    e = etat(_getter({}))                      # getter qui ne renvoie rien d'utile
    assert e["state"] == "CONNECTED" and analyser(e)["probleme"] is False


# --- Watcher ---

def test_watcher_alerte_puis_retablit():
    seq = [{"state": "CONNECTED"}, {"state": "OFFLINE"}, {"state": "CONNECTED"}]
    i = {"n": 0}

    def getter():
        d = seq[min(i["n"], len(seq) - 1)]
        i["n"] += 1
        return d

    notifs = []
    w = StarlinkWatcher(getter, notifs.append)
    w.un_tour()        # connecté : rien
    w.un_tour()        # coupure : alerte
    w.un_tour()        # rétabli : message de retour
    assert any("interrompue" in n for n in notifs)
    assert any("rétablie" in n for n in notifs)


def test_watcher_pas_de_repetition():
    w = StarlinkWatcher(_getter({"state": "OFFLINE"}), notify=lambda m: None)
    assert len(w.un_tour()) == 1       # 1re fois : alerte
    assert w.un_tour() == []           # même problème : silencieux


def test_watcher_antenne_injoignable():
    def boom():
        raise OSError("pas de gRPC")
    assert StarlinkWatcher(boom, lambda m: None).un_tour() == []


# --- Outil / fabrique ---

def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "STARLINK", False)
    assert build_starlink_tools(getter=_getter({})) == []
    assert make_starlink_watcher(lambda m: None) is None


def test_outil_etat_internet(monkeypatch):
    monkeypatch.setattr(config, "STARLINK", True)
    tools = {t.name: t for t in build_starlink_tools(getter=_getter({"state": "CONNECTED", "latence_ms": 35}))}
    assert "Starlink : connecté" in tools["etat_internet"].run()
