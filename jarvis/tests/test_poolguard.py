"""Tests de la surveillance piscine (alerte de sécurité, échoue vers l'alerte)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import poolguard  # noqa: E402
from poolguard import (PoolGuard, PoolWatcher, analyser_frigate,  # noqa: E402
                       build_pool_tools, make_escalader, make_poolguard)

ZONES = ("bassin",)


@pytest.fixture(autouse=True)
def _reset():
    poolguard._GUARD = None
    yield
    poolguard._GUARD = None


class FakeHome:
    def __init__(self):
        self.appels = []

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id, data))


class FakeStore:
    def __init__(self):
        self.data = {}

    def save(self):
        pass


class FakeTimer:
    def __init__(self, delai, fn):
        self.delai, self.fn = delai, fn
        self.demarre = self.annule = False

    def start(self):
        self.demarre = True

    def cancel(self):
        self.annule = True


def _event(label="person", zones=("bassin",), camera="piscine", type_="new"):
    return json.dumps({"type": type_,
                       "after": {"label": label, "camera": camera, "current_zones": list(zones)}}).encode()


# --- Analyse Frigate ---

def test_personne_dans_le_bassin():
    info = analyser_frigate(_event(), ZONES)
    assert info == {"camera": "piscine", "zones": ["bassin"]}


def test_ignore_non_personne():
    assert analyser_frigate(_event(label="dog"), ZONES) is None


def test_ignore_hors_zone():
    assert analyser_frigate(_event(zones=("terrasse",)), ZONES) is None


def test_ignore_fin_d_evenement():
    assert analyser_frigate(_event(type_="end"), ZONES) is None


def test_filtre_camera():
    assert analyser_frigate(_event(camera="entree"), ZONES, camera="piscine") is None


def test_json_invalide():
    assert analyser_frigate(b"pas du json", ZONES) is None


# --- Réaction ---

def _guard(home, escalader=None, timers=None, clock=None, **s):
    settings = {"sirene": "siren.piscine", "lumieres": ["light.terrasse"],
                "baies": ["lock.baie_salon"], "haut_parleur": "media_player.maison",
                "urgence_delai": 15, "cooldown": 20, **s}
    minuteur = None
    if timers is not None:
        def minuteur(delai, fn):
            t = FakeTimer(delai, fn)
            timers.append(t)
            return t
    notifs = []
    g = PoolGuard(home, notifs.append, FakeStore(), settings=settings, escalader=escalader,
                  horloge=clock or (lambda: 0.0), minuteur=minuteur)
    return g, notifs


def test_detection_declenche_alarme_lumieres_baies():
    home = FakeHome()
    g, notifs = _guard(home)
    out = g.sur_detection({"camera": "piscine"})
    actions = [(a[0], a[1]) for a in home.appels]
    assert ("siren", "turn_on") in actions          # alarme hurlante
    assert ("light", "turn_on") in actions          # lumières
    assert ("lock", "unlock") in actions            # baies vitrées déverrouillées
    assert any("PISCINE" in n for n in notifs)
    assert "alarme" in out["faites"] and "baies déverrouillées" in out["faites"]


def test_cooldown_evite_la_repetition():
    clock = {"t": 0.0}
    g, _ = _guard(FakeHome(), clock=lambda: clock["t"])
    g.sur_detection({})
    assert g.sur_detection({}) == {"ignore": "cooldown"}   # tout de suite après : ignoré
    clock["t"] = 25
    assert "faites" in g.sur_detection({})                 # après le cooldown : re-réagit


def test_pas_d_escalade_sans_mode_urgence():
    timers = []
    g, _ = _guard(FakeHome(), escalader=lambda m: None, timers=timers)
    out = g.sur_detection({})
    assert out["escalade_programmee"] is False and timers == []


def test_escalade_programmee_si_urgence_armee():
    timers, appels = [], []
    g, notifs = _guard(FakeHome(), escalader=lambda m: appels.append(m), timers=timers)
    g.armer_urgence()
    out = g.sur_detection({})
    assert out["escalade_programmee"] is True
    assert len(timers) == 1 and timers[0].demarre and timers[0].delai == 15
    assert appels == []                              # pas encore : le décompte tourne
    timers[0].fn()                                   # le décompte arrive à terme
    assert appels and any("112" in m for m in appels)
    assert any("alertés" in n for n in notifs)


def test_annuler_stoppe_l_escalade():
    timers = []
    g, _ = _guard(FakeHome(), escalader=lambda m: None, timers=timers)
    g.armer_urgence()
    g.sur_detection({})
    msg = g.annuler()
    assert timers[0].annule is True and "annulée" in msg


def test_desarmer_annule_le_timer():
    timers = []
    g, _ = _guard(FakeHome(), escalader=lambda m: None, timers=timers)
    g.armer_urgence()
    g.sur_detection({})
    g.desarmer_urgence()
    assert timers[0].annule is True


def test_couper_alarme_eteint_la_sirene():
    home = FakeHome()
    g, _ = _guard(home)
    g.couper_alarme()
    assert ("siren", "turn_off", "siren.piscine", {}) in home.appels


def test_escalade_echoue_previent_d_appeler_112():
    def boom(m):
        raise RuntimeError("réseau coupé")
    timers = []
    g, notifs = _guard(FakeHome(), escalader=boom, timers=timers)
    g.armer_urgence()
    g.sur_detection({})
    timers[0].fn()
    assert any("APPELEZ LE 112" in n for n in notifs)   # on ne reste jamais silencieux


# --- Escalade : n'appelle pas le 112 toute seule, relaie à un service configuré ---

def test_escalader_notifie_et_poste_webhook():
    notifs, postes = [], []
    esc = make_escalader(notifs.append, webhook="http://maison/alerte",
                         poster=lambda url, charge: postes.append((url, json.loads(charge))))
    esc("message test")
    assert any("URGENCE PISCINE" in n for n in notifs)
    assert postes[0][0] == "http://maison/alerte" and postes[0][1]["alerte"] == "piscine"


def test_escalader_sans_webhook_notifie_seulement():
    notifs = []
    make_escalader(notifs.append)("x")
    assert notifs and len(notifs) == 1


# --- Veille MQTT + fabrique/outils ---

def test_watcher_traite_un_evenement():
    home = FakeHome()
    g, _ = _guard(home)
    PoolWatcher(g, ZONES).traiter(_event())
    assert any(a[0] == "siren" for a in home.appels)   # la détection a déclenché la réaction


def test_build_pool_tools_vide_sans_config(monkeypatch):
    import config
    monkeypatch.setattr(config, "POOL", False)
    assert build_pool_tools(FakeHome(), lambda m: None) == []


def test_build_pool_tools_et_make_partagent_la_garde(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "POOL", True)
    monkeypatch.setattr(config, "POOL_ZONES", ZONES)
    monkeypatch.setattr(config, "POOL_CAMERA", "")
    monkeypatch.setattr(config, "POOL_FILE", tmp_path / "piscine.json")
    monkeypatch.setattr(config, "POOL_WEBHOOK", "")
    noms = {t.name for t in build_pool_tools(FakeHome(), lambda m: None)}
    assert {"armer_urgence_piscine", "annuler_alerte_piscine", "couper_alarme_piscine"} <= noms
    watcher = make_poolguard(FakeHome(), lambda m: None)
    assert isinstance(watcher, PoolWatcher) and watcher.guard is poolguard._GUARD
