"""Tests de la détection d'instabilité Wi-Fi (symptôme de déauth)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from wifiwatch import (StabilityTracker, WifiStabilityWatcher,  # noqa: E402
                       make_wifi_watcher)


def _tracker(clock, seuil=4, fenetre=120):
    return StabilityTracker(seuil=seuil, fenetre_s=fenetre, horloge=lambda: clock["t"])


def test_premier_passage_apprend_sans_alerter():
    t = _tracker({"t": 0})
    assert t.observer({"cam", "tv", "phone"}) == []


def test_une_deconnexion_isolee_ne_declenche_pas():
    clock = {"t": 0}
    t = _tracker(clock)
    t.observer({"cam", "tv"})
    assert t.observer({"tv"}) == []          # cam partie une fois : pas encore


def test_flapping_declenche_apres_le_seuil():
    clock = {"t": 0}
    t = _tracker(clock, seuil=3)
    t.observer({"cam"})                       # apprentissage
    alertes = []
    for i in range(3):                        # cam disparaît puis revient, 3 fois
        clock["t"] = i * 2 + 1
        alertes += t.observer(set())          # cam partie (c'est ici que le seuil se franchit)
        alertes += t.observer({"cam"})        # cam revenue
    assert any("cam" in x and "déconnecté" in x for x in alertes)


def test_deconnexion_de_masse():
    clock = {"t": 0}
    t = _tracker(clock)
    t.observer({"cam", "tv", "phone", "nas"})
    alertes = t.observer({"nas"})             # 3 partis d'un coup
    assert any("déauthentification" in x for x in alertes)


def test_flapping_hors_fenetre_oublie():
    clock = {"t": 0}
    t = _tracker(clock, seuil=3, fenetre=10)
    t.observer({"cam"})
    clock["t"] = 1
    t.observer(set()); t.observer({"cam"})    # 1 chute à t=1
    clock["t"] = 100                          # bien après la fenêtre
    t.observer(set()); a = t.observer({"cam"})  # 1 chute à t=100
    assert a == []                            # les anciennes chutes ont expiré


# --- Watcher ---

class FauxClient:
    def __init__(self, suites):
        self._suites = suites
        self._i = 0

    def appareils(self):
        s = self._suites[min(self._i, len(self._suites) - 1)]
        self._i += 1
        return [{"nom": n, "mac": n, "actif": True} for n in s]


def test_watcher_notifie_sur_masse():
    clock = {"t": 0}
    client = FauxClient([{"a", "b", "c", "d"}, {"a"}])   # 3 partis au 2e tour
    notifs = []
    w = WifiStabilityWatcher(client, notifs.append, _tracker(clock))
    w.un_tour()        # apprentissage
    w.un_tour()        # masse
    assert any("déauthentification" in n for n in notifs)


def test_watcher_client_en_panne():
    class Ko:
        def appareils(self):
            raise OSError("freebox down")
    w = WifiStabilityWatcher(Ko(), lambda m: None, StabilityTracker())
    assert w.un_tour() == []          # pas de plantage


# --- Fabrique ---

def test_make_desactive(monkeypatch):
    monkeypatch.setattr(config, "WIFI_STABILITE", False)
    assert make_wifi_watcher(lambda m: None) is None


def test_make_sans_freebox(monkeypatch):
    monkeypatch.setattr(config, "WIFI_STABILITE", True)
    monkeypatch.setattr(config, "FREEBOX_TOKEN", "")
    assert make_wifi_watcher(lambda m: None) is None
