"""Tests de la radio SDR : avions au-dessus (ADS-B) et météo radio locale."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from radio import (_haversine, avions, build_radio_tools,  # noqa: E402
                   message_survol, survol)

# Maison fictive
LAT, LON = 48.85, 2.35


def _data():
    return {"aircraft": [
        {"hex": "abc", "flight": "AFR456 ", "alt_baro": 34000, "lat": 48.86, "lon": 2.36, "track": 315},
        {"hex": "def", "flight": "BAW12", "alt_baro": 38000, "lat": 49.50, "lon": 3.50, "track": 90},
        {"hex": "ghi", "flight": "NOPOS", "alt_baro": 10000},          # sans position : ignoré
        {"hex": "jkl", "flight": "ONGND", "alt_baro": "ground", "lat": 48.85, "lon": 2.35},  # au sol
    ]}


def test_haversine_coherent():
    assert 0 <= _haversine(48.85, 2.35, 48.86, 2.36) < 2        # ~1,4 km


def test_avions_tries_et_filtres():
    out = avions(_data(), LAT, LON)
    assert [a["vol"] for a in out] == ["AFR456", "BAW12"]        # NOPOS et ONGND écartés
    assert out[0]["altitude_m"] == round(34000 * 0.3048)         # pieds -> mètres
    assert out[0]["cap"] == "nord-ouest"                         # track 315


def test_survol_dans_le_rayon():
    a = survol(_data(), LAT, LON, rayon_km=15)
    assert a["vol"] == "AFR456"


def test_survol_hors_rayon():
    assert survol(_data(), LAT, LON, rayon_km=0.5) is None       # le plus proche est à ~1,4 km


def test_message_honnete_sans_destination():
    a = survol(_data(), LAT, LON, 15)
    msg = message_survol(a)
    assert "AFR456" in msg and "m d'altitude" in msg
    assert "destination n'est pas dans le signal" in msg         # on n'invente pas « vers New York »


# --- Outils ---

def test_pas_d_outils_sans_config(monkeypatch):
    monkeypatch.setattr(config, "ADSB", False)
    monkeypatch.setattr(config, "METEO_RADIO", {})
    assert build_radio_tools(None) == []


def test_avion_au_dessus(monkeypatch):
    monkeypatch.setattr(config, "ADSB", True)
    monkeypatch.setattr(config, "METEO_RADIO", {})
    monkeypatch.setattr(config, "ADSB_LAT", LAT)
    monkeypatch.setattr(config, "ADSB_LON", LON)
    monkeypatch.setattr(config, "ADSB_RAYON_KM", 15)
    monkeypatch.setattr(config, "ADSB_URL", "http://x")
    tools = {t.name: t for t in build_radio_tools(None, fetch=lambda url: _data())}
    assert "AFR456" in tools["avion_au_dessus"].run()


def test_avion_recepteur_absent(monkeypatch):
    monkeypatch.setattr(config, "ADSB", True)
    monkeypatch.setattr(config, "METEO_RADIO", {})
    monkeypatch.setattr(config, "ADSB_LAT", LAT)
    monkeypatch.setattr(config, "ADSB_LON", LON)

    def boom(url):
        raise OSError("refusé")
    tools = {t.name: t for t in build_radio_tools(None, fetch=boom)}
    assert "récepteur ADS-B" in tools["avion_au_dessus"].run()


def test_ciel_vide(monkeypatch):
    monkeypatch.setattr(config, "ADSB", True)
    monkeypatch.setattr(config, "METEO_RADIO", {})
    monkeypatch.setattr(config, "ADSB_LAT", LAT)
    monkeypatch.setattr(config, "ADSB_LON", LON)
    monkeypatch.setattr(config, "ADSB_RAYON_KM", 15)
    tools = {t.name: t for t in build_radio_tools(None, fetch=lambda url: {"aircraft": []})}
    assert "Aucun avion" in tools["avion_au_dessus"].run()


class FakeHome:
    configured = True

    def __init__(self, etats):
        self._e = etats

    def states(self):
        return [{"entity_id": k, "state": v} for k, v in self._e.items()]


def test_meteo_radio(monkeypatch):
    monkeypatch.setattr(config, "ADSB", False)
    monkeypatch.setattr(config, "METEO_RADIO",
                        {"temperature": "sensor.t", "humidite": "sensor.h", "pression": "sensor.p"})
    home = FakeHome({"sensor.t": "12.3", "sensor.h": "78", "sensor.p": "1013"})
    tools = {t.name: t for t in build_radio_tools(home)}
    out = tools["meteo_radio"].run()
    assert "12.3 °C" in out and "78 %" in out and "1013 hPa" in out
