"""Tests du tableau de bord : assemblage des données et serveur HTTP local."""

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import dashboard  # noqa: E402
import skills  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


@pytest.fixture(autouse=True)
def persona_film(monkeypatch):
    monkeypatch.setattr(config, "STYLE", "film")
    monkeypatch.setattr(config, "TITLE", "Monsieur")
    monkeypatch.setattr(config, "CITY", "Paris")
    monkeypatch.setattr(config, "OFFLINE", False)


def now_at(hour=9, minute=41):
    return lambda: datetime(2026, 11, 13, hour, minute, tzinfo=PARIS)


def provider(tmp_path, **kw):
    reminders = skills.Reminders(tmp_path / "r.json", now=kw.get("now", now_at()))
    lists = skills.Lists(tmp_path / "l.json")
    return dashboard.StateProvider(
        reminders, lists, home=kw.get("home"), sentinel=kw.get("sentinel"),
        now=kw.get("now", now_at()),
        weather=kw.get("weather", lambda: "À Paris : 6 degrés, ciel dégagé."),
        pc_status=kw.get("pc", lambda: "Disque : 180 Go libres."),
        clock=kw.get("clock", lambda: 0.0)), reminders, lists


# --- Assemblage ---

def test_state_basic_fields(tmp_path):
    p, reminders, lists = provider(tmp_path)
    reminders.add("Sortir le linge", date_heure="2026-11-13 10:00")
    reminders.add("Demain", date_heure="2026-11-14 08:00")
    lists.add("lait")
    lists.add("pain")
    s = p.state()
    assert s["heure"] == "09:41"
    assert s["date"] == "vendredi 13 novembre"
    assert "Monsieur" in s["salutation"]
    assert s["meteo"]["texte"].startswith("À Paris")
    assert s["rappels"] == [{"heure": "10:00", "texte": "Sortir le linge"}]  # pas demain
    assert s["courses"] == 2
    assert "Go libres" in s["pc"]


def test_weather_hidden_without_city(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CITY", "")
    p, *_ = provider(tmp_path)
    assert p.state()["meteo"] == {}


def test_home_overview(tmp_path):
    states = [
        {"entity_id": "light.salon", "state": "on", "attributes": {"friendly_name": "Lampe salon"}},
        {"entity_id": "lock.porte", "state": "locked", "attributes": {"friendly_name": "Porte"}},
        {"entity_id": "sensor.temp", "state": "21", "attributes": {"friendly_name": "Salon", "unit_of_measurement": "°C"}},
    ]
    home = NS(configured=True, states=lambda: states, _name=lambda e: e["attributes"]["friendly_name"])
    p, *_ = provider(tmp_path, home=home)
    m = p.state()["maison"]
    assert m["configure"] is True
    assert {"nom": "Lampe salon", "etat": "on"} in m["appareils"]
    assert {"nom": "Porte", "etat": "lock"} in m["appareils"]
    assert m["temperatures"] == [{"nom": "Salon", "valeur": "21°"}]


def test_home_absent_or_unconfigured(tmp_path):
    p, *_ = provider(tmp_path, home=NS(configured=False))
    assert p.state()["maison"] == {"configure": False, "appareils": []}


def test_security_overview_levels(tmp_path):
    sentinel = NS(report=lambda: "Pare-feu actif. ATTENTION, pare-feu désactivé. 7 appareils vus")
    p, *_ = provider(tmp_path, sentinel=sentinel)
    secu = p.state()["securite"]
    assert {"libelle": "Pare-feu actif", "niveau": "ok"} in secu
    assert {"libelle": "pare-feu désactivé", "niveau": "crit"} in secu


def test_caches_limit_expensive_calls(tmp_path):
    calls = {"w": 0, "pc": 0}

    def weather():
        calls["w"] += 1
        return "À Paris : 6 degrés."

    def pc():
        calls["pc"] += 1
        return "ok"

    clock = NS(t=0.0)
    p, *_ = provider(tmp_path, weather=weather, pc=pc, clock=lambda: clock.t)
    for _ in range(5):
        p.state()
    assert calls["w"] == 1 and calls["pc"] == 1       # mis en cache
    clock.t = 1000                                     # bien après les deux TTL
    p.state()
    assert calls["w"] == 2 and calls["pc"] == 2


def test_failing_source_keeps_dashboard_alive(tmp_path):
    def boom():
        raise OSError("réseau")

    p, *_ = provider(tmp_path, weather=boom, pc=boom)
    s = p.state()                                      # ne doit pas lever
    assert s["meteo"] == {} and s["pc"] == {}


# --- Serveur HTTP ---

def test_server_serves_html_and_json(tmp_path):
    p, reminders, _ = provider(tmp_path)
    reminders.add("Café", date_heure="2026-11-13 10:00")
    server = dashboard.make_server(p, "127.0.0.1", 0)  # port libre au hasard
    import threading
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        html = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).read().decode()
        assert "J.A.R.V.I.S" in html and "/api/etat" in html
        data = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=5).read())
        assert data["heure"] == "09:41"
        assert data["rappels"][0]["texte"] == "Café"
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/secret", timeout=5)
        assert exc.value.code == 404
    finally:
        server.shutdown()


def test_cameras_dans_l_etat(tmp_path, monkeypatch):
    import camera
    p, reminders, _ = provider(tmp_path)
    book = camera.CameraBook(tmp_path / "cam.json")
    book.add("jardin", "rtsp://x/stream")
    p.cameras = book
    assert "jardin" in p.state()["cameras"]
    # snapshot : on capture une image (grab_frame simulé)
    monkeypatch.setattr(camera, "grab_frame", lambda url: b"IMG-" + url.encode())
    assert p.snapshot("jardin") == b"IMG-rtsp://x/stream"
    assert p.snapshot("inconnue") is None


def test_token_protege_le_tableau_de_bord(tmp_path):
    import threading
    p, reminders, _ = provider(tmp_path)
    server = dashboard.make_server(p, "127.0.0.1", 0, token="s3cret")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        # Sans jeton -> 401
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat", timeout=5)
        assert exc.value.code == 401
        # Mauvais jeton -> 401
        with pytest.raises(urllib.error.HTTPError) as exc2:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/etat?jeton=faux", timeout=5)
        assert exc2.value.code == 401
        # Bon jeton -> 200
        data = json.loads(urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/etat?jeton=s3cret", timeout=5).read())
        assert "heure" in data
    finally:
        server.shutdown()


def test_html_escapes_values(tmp_path):
    """Un nom de rappel piégé ne doit pas pouvoir injecter de HTML (XSS)."""
    html = dashboard.HTML_FILE.read_text()
    # Les données ne sont PAS injectées côté serveur : la page les récupère et les échappe
    # elle-même avec esc() avant de les insérer.
    assert "replace(/[&<>]/g" in html
    assert "${esc(" in html and "esc(r.texte)" in html
