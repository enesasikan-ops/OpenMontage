"""Tests du mode détente (ambiance apaisante déclenchée par toi, pas devinée)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from comfort import Comfort, build_comfort_tools  # noqa: E402


class FauxHome:
    def __init__(self):
        self.appels = []

    def call(self, domaine, service, entity_id, **data):
        self.appels.append((domaine, service, entity_id, data))


def _config_detente(monkeypatch, lumieres=("light.salon",), niveau=40,
                    media="media_player.salon", source="spotify:playlist:calme"):
    monkeypatch.setattr(config, "DETENTE_LUMIERES", tuple(lumieres))
    monkeypatch.setattr(config, "DETENTE_NIVEAU", niveau)
    monkeypatch.setattr(config, "DETENTE_MEDIA", media)
    monkeypatch.setattr(config, "DETENTE_SOURCE", source)


def test_baisse_les_lumieres_au_niveau_configure(monkeypatch):
    _config_detente(monkeypatch, media="", source="")
    home = FauxHome()
    out = Comfort(home).detente()
    assert ("light", "turn_on", ["light.salon"], {"brightness_pct": 40}) in home.appels
    assert "40 %" in out


def test_niveau_explicite_prioritaire_et_plafonne(monkeypatch):
    _config_detente(monkeypatch, media="", source="")
    home = FauxHome()
    Comfort(home).detente(999)
    assert home.appels[0][3] == {"brightness_pct": 100}   # jamais plus de 100 %


def test_joue_la_musique_douce(monkeypatch):
    _config_detente(monkeypatch, lumieres=())
    home = FauxHome()
    out = Comfort(home).detente()
    appel = [a for a in home.appels if a[0] == "media_player"][0]
    assert appel[1] == "play_media" and appel[2] == "media_player.salon"
    assert appel[3]["media_content_id"] == "spotify:playlist:calme"
    assert "musique" in out


def test_media_sans_source_lance_la_lecture(monkeypatch):
    _config_detente(monkeypatch, lumieres=(), source="")
    home = FauxHome()
    Comfort(home).detente()
    assert ("media_player", "media_play", "media_player.salon", {}) in home.appels


def test_non_configure(monkeypatch):
    _config_detente(monkeypatch, lumieres=(), media="", source="")
    out = Comfort(FauxHome()).detente()
    assert "pas configuré" in out


def test_echec_home_message_clair(monkeypatch):
    _config_detente(monkeypatch, media="", source="")

    class HomeKo:
        def call(self, *a, **k):
            raise OSError("HA injoignable")

    out = Comfort(HomeKo()).detente()
    assert "pas réussi" in out


# --- L'outil n'existe que si une ambiance est configurée ---

def test_pas_d_outil_sans_config(monkeypatch):
    monkeypatch.setattr(config, "DETENTE_LUMIERES", ())
    monkeypatch.setattr(config, "DETENTE_MEDIA", "")
    assert build_comfort_tools(FauxHome()) == []


def test_outil_present_si_lumieres(monkeypatch):
    monkeypatch.setattr(config, "DETENTE_LUMIERES", ("light.salon",))
    monkeypatch.setattr(config, "DETENTE_MEDIA", "")
    tools = build_comfort_tools(FauxHome())
    assert len(tools) == 1 and tools[0].name == "mode_detente"
