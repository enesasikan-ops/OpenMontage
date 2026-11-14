"""Tests du suivi audio multi-room (le son qui marche avec toi)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audiofollow  # noqa: E402
import config  # noqa: E402
from audiofollow import (AudioFollow, Piece, PresenceAudioWatcher, Snapcast,  # noqa: E402
                         build_audio_tools, make_audio_follow, niveaux_cibles)

CUISINE = Piece("cuisine", "binary_sensor.cuisine_presence", "media_player.snapcast_cuisine")
SALON = Piece("salon", "binary_sensor.salon_presence", "media_player.snapcast_salon")
PIECES = [CUISINE, SALON]

PIECES_JSON = {
    "cuisine": {"presence": CUISINE.presence, "enceinte": CUISINE.enceinte},
    "salon": {"presence": SALON.presence, "enceinte": SALON.enceinte},
}


@pytest.fixture(autouse=True)
def _reset_singleton():
    audiofollow._CTRL = None
    yield
    audiofollow._CTRL = None


class FakeHome:
    def __init__(self, etats=None):
        self._etats = etats or []
        self.appels = []

    def states(self):
        return self._etats

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id, data))


def _ctrl(present=0.35, absent=0.0):
    home = FakeHome()
    c = AudioFollow(PIECES, regler=lambda e, n: home.appels.append((e, n)),
                    present=present, absent=absent)
    return c, home.appels


# --- Calcul des niveaux ---

def test_niveaux_cibles():
    out = niveaux_cibles(PIECES, {"salon"}, 0.35, 0.0)
    assert out == {"cuisine": 0.0, "salon": 0.35}


# --- Contrôleur ---

def test_inactif_ne_fait_rien():
    c, appels = _ctrl()
    assert c.router({"salon"}) == {} and appels == []


def test_route_vers_la_piece_occupee():
    c, appels = _ctrl()
    c.activer()
    change = c.router({"salon"})
    assert change == {"cuisine": 0.0, "salon": 0.35}
    assert ("media_player.snapcast_salon", 0.35) in appels
    assert ("media_player.snapcast_cuisine", 0.0) in appels


def test_rien_si_rien_ne_joue():
    c, appels = _ctrl()
    c.activer()
    assert c.router({"salon"}, joue=False) == {} and appels == []


def test_pas_d_appel_redondant():
    c, appels = _ctrl()
    c.activer()
    c.router({"salon"})
    appels.clear()
    assert c.router({"salon"}) == {}      # état déjà posé
    assert appels == []


def test_le_son_marche_avec_toi():
    c, appels = _ctrl()
    c.activer()
    c.router({"cuisine"})                  # tu es en cuisine
    appels.clear()
    change = c.router({"salon"})           # tu passes au salon
    assert change == {"cuisine": 0.0, "salon": 0.35}


def test_deux_pieces_occupees_restent_audibles():
    c, _ = _ctrl()
    c.activer()
    assert c.router({"cuisine", "salon"}) == {"cuisine": 0.35, "salon": 0.35}


def test_vers_commande_explicite_ignore_actif():
    c, appels = _ctrl()
    change = c.vers({"salon"})             # inactif, mais commande directe
    assert change == {"cuisine": 0.0, "salon": 0.35}


def test_arreter_ne_touche_pas_aux_volumes():
    c, appels = _ctrl()
    c.activer()
    c.router({"salon"})
    appels.clear()
    c.arreter()
    assert appels == [] and c.actif is False


# --- Backend Snapcast (JSON-RPC injecté) ---

def test_snapcast_clients_et_volume():
    envoyes = []
    status = {"result": {"server": {"groups": [
        {"clients": [{"id": "ab:cd", "config": {"name": "cuisine"}},
                     {"id": "ef:gh", "host": {"name": "salon"}}]}]}}}

    def transport(req):
        envoyes.append(req)
        return status if req["method"] == "Server.GetStatus" else {"result": "ok"}

    snap = Snapcast("snap.local", transport=transport)
    assert snap.clients() == {"cuisine": "ab:cd", "salon": "ef:gh"}
    snap.set_volume("ab:cd", 35)
    dernier = envoyes[-1]
    assert dernier["method"] == "Client.SetVolume"
    assert dernier["params"] == {"id": "ab:cd", "volume": {"percent": 35, "muted": False}}


def test_snapcast_mute_a_zero():
    envoyes = []
    Snapcast("x", transport=lambda r: envoyes.append(r) or {"result": 1}).set_volume("c1", 0)
    assert envoyes[-1]["params"]["volume"] == {"percent": 0, "muted": True}


# --- Backend Home Assistant (via _setter) ---

def test_setter_ha_regle_le_media_player(monkeypatch):
    monkeypatch.setattr(config, "SNAPSERVER", "")
    home = FakeHome()
    regler = audiofollow._setter(home)
    regler("media_player.snapcast_salon", 0.35)
    assert home.appels == [("media_player", "volume_set", "media_player.snapcast_salon",
                            {"volume_level": 0.35})]


# --- Veille de présence ---

def test_watcher_route_selon_presence_et_lecture():
    etats = [
        {"entity_id": "binary_sensor.cuisine_presence", "state": "off"},
        {"entity_id": "binary_sensor.salon_presence", "state": "on"},
        {"entity_id": "media_player.snapcast_salon", "state": "playing"},
    ]
    home = FakeHome(etats)
    c = AudioFollow(PIECES, regler=lambda e, n: None)
    c.activer()
    w = PresenceAudioWatcher(home, c, PIECES)
    assert w.un_tour() == {"cuisine": 0.0, "salon": 0.35}


def test_watcher_silencieux_si_rien_ne_joue():
    etats = [{"entity_id": "binary_sensor.salon_presence", "state": "on"}]  # aucun media_player playing
    c = AudioFollow(PIECES, regler=lambda e, n: None)
    c.activer()
    assert PresenceAudioWatcher(FakeHome(etats), c, PIECES).un_tour() == {}


# --- Fabrique + outils ---

def test_make_audio_follow_desactive(monkeypatch):
    monkeypatch.setattr(config, "AUDIO_FOLLOW", False)
    assert make_audio_follow(FakeHome()) is None


def test_make_audio_follow_pret(monkeypatch):
    monkeypatch.setattr(config, "AUDIO_FOLLOW", True)
    monkeypatch.setattr(config, "AUDIO_PIECES", PIECES_JSON)
    monkeypatch.setattr(config, "SNAPSERVER", "")
    monkeypatch.setattr(config, "AUDIO_PRESENT", 0.35)
    monkeypatch.setattr(config, "AUDIO_ABSENT", 0.0)
    monkeypatch.setattr(config, "AUDIO_INTERVAL", 3.0)
    w = make_audio_follow(FakeHome())
    assert isinstance(w, PresenceAudioWatcher) and w.controleur.actif is True


def test_pas_d_outils_sans_config(monkeypatch):
    monkeypatch.setattr(config, "AUDIO_PIECES", {})
    assert build_audio_tools(FakeHome()) == []


def test_outils_suivi(monkeypatch):
    monkeypatch.setattr(config, "AUDIO_PIECES", PIECES_JSON)
    monkeypatch.setattr(config, "SNAPSERVER", "")
    monkeypatch.setattr(config, "AUDIO_PRESENT", 0.35)
    monkeypatch.setattr(config, "AUDIO_ABSENT", 0.0)
    home = FakeHome()
    tools = {t.name: t for t in build_audio_tools(home)}
    assert set(tools) == {"suivez_moi", "arrete_de_suivre", "son_dans_la_piece"}
    assert "suivra" in tools["suivez_moi"].run()
    out = tools["son_dans_la_piece"].run(piece="salon")
    assert "salon" in out.lower()
    # le son a bien été poussé au salon via HA
    assert ("media_player", "volume_set", "media_player.snapcast_salon",
            {"volume_level": 0.35}) in home.appels


def test_outil_piece_inconnue(monkeypatch):
    monkeypatch.setattr(config, "AUDIO_PIECES", PIECES_JSON)
    monkeypatch.setattr(config, "SNAPSERVER", "")
    tools = {t.name: t for t in build_audio_tools(FakeHome())}
    out = tools["son_dans_la_piece"].run(piece="grenier")
    assert "grenier" in out and "cuisine" in out and "salon" in out
