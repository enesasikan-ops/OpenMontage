"""Tests de la maison connectée, avec un faux Home Assistant (aucun réseau)."""

import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace as NS


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import skills  # noqa: E402
from smarthome import SmartHome, _match, _norm, build_smarthome  # noqa: E402
from tools import build_tools  # noqa: E402


def entity(eid, name, state="off", **attrs):
    return {"entity_id": eid, "state": state, "attributes": {"friendly_name": name, **attrs}}


HOUSE = [
    entity("light.salon", "Lampe du salon", "on"),
    entity("light.salon_plafond", "Plafonnier salon", "off"),
    entity("light.chambre", "Lumière chambre", "off"),
    entity("switch.cafe", "Cafetière", "off"),
    entity("cover.garage", "Porte du garage", "closed"),
    entity("cover.volet_salon", "Volet salon", "open"),
    entity("lock.entree", "Serrure entrée", "locked"),
    entity("sensor.temp_salon", "Température salon", "21", unit_of_measurement="°C"),
    entity("scene.cinema", "Ambiance cinéma"),
]


class FakeHA:
    """Imite l'accès officiel de Home Assistant. Enregistre les ordres envoyés."""

    def __init__(self, states=None, fail=None):
        self.store = {e["entity_id"]: dict(e) for e in (states or HOUSE)}
        self.fail = fail
        self.calls = []

    def __call__(self, method, path, body=None):
        if self.fail:
            raise self.fail
        if method == "GET" and path == "/api/states":
            return list(self.store.values())
        if method == "POST" and path.startswith("/api/services/"):
            domain, service = path.split("/")[3], path.split("/")[4]
            self.calls.append((domain, service, body["entity_id"],
                               {k: v for k, v in body.items() if k != "entity_id"}))
            return None
        raise AssertionError(path)


def home(states=None, fail=None):
    ha = FakeHA(states, fail)
    return SmartHome("http://ha.local:8123", "jeton-test", request=ha), ha


# --- Reconnaissance des noms ---

def test_norm_strips_accents_and_articles():
    assert _norm("la Température du Salon") == "temperature salon"
    assert _match("salon", "Lampe du salon") > 0
    assert _match("salon", "Lumière chambre") == 0


def test_resolve_matches_all_lights_of_a_room():
    h, _ = home()
    salon = {e["entity_id"] for e in h.resolve("salon", ("light",))}
    assert salon == {"light.salon", "light.salon_plafond"}  # les deux lampes du salon


def test_resolve_all_keyword():
    h, _ = home()
    assert len(h.resolve("tout", ("light", "switch"))) == 4
    assert len(h.resolve("", ("light",))) == 3


def test_resolve_unknown_returns_empty():
    h, _ = home()
    assert h.resolve("cave", ("light",)) == []


# --- Actions ---

def test_turn_on_room_acts_on_all_matching():
    h, ha = home()
    msg = h.turn_on("salon")
    assert "Lampe du salon" in msg and "Plafonnier salon" in msg
    services = {(d, s) for d, s, *_ in ha.calls}
    assert services == {("light", "turn_on")}
    sent = {eid for _, _, ids, _ in ha.calls for eid in ids}
    assert sent == {"light.salon", "light.salon_plafond"}


def test_turn_off_everything_spans_domains():
    h, ha = home()
    h.turn_off("tout")
    domains = {d for d, _, _, _ in ha.calls}
    assert "light" in domains and "switch" in domains  # un ordre par type d'appareil


def test_set_brightness_and_zero_turns_off():
    h, ha = home()
    assert "30 %" in h.set_brightness("chambre", 30)
    assert ha.calls[0] == ("light", "turn_on", ["light.chambre"], {"brightness_pct": 30})
    h2, ha2 = home()
    h2.set_brightness("chambre", 0)
    assert ha2.calls[0][1] == "turn_off"
    assert "entre 0 et 100" in home()[0].set_brightness("chambre", "beaucoup")


def test_cover_and_lock():
    h, ha = home()
    assert "Ouvert" in h.open_cover("garage")
    assert ha.calls[0] == ("cover", "open_cover", ["cover.garage"], {})
    assert "Verrouillé" in home()[0].lock("entrée")
    assert "Déverrouillé" in home()[0].unlock("entrée")


def test_run_scene():
    h, ha = home()
    assert "cinéma" in h.run_scene("cinéma")
    assert ha.calls[0][:2] == ("scene", "turn_on")
    assert "ne trouve pas" in home()[0].run_scene("fête")


# --- Lecture ---

def test_status_summary_and_specific():
    h, _ = home()
    summary = h.status()
    assert "Lampe du salon" in summary and "21" in summary
    assert "21 °C" in h.status("température salon")
    assert "fermé" in h.status("garage")
    assert "ne trouve pas" in h.status("piscine")


# --- Pannes et sécurité ---

def test_not_configured():
    h = SmartHome("", "")
    assert not h.configured
    assert "n'est pas configurée" in h.turn_on("salon")


def test_network_down_is_friendly():
    h, _ = home(fail=urllib.error.URLError("refused"))
    assert "joindre la maison" in h.turn_on("salon")


def test_bad_token_is_explained():
    h, _ = home(fail=urllib.error.HTTPError("u", 401, "no", {}, None))
    assert "jeton" in h.turn_on("salon")


# --- Intégration avec Jarvis : confirmation des actions sensibles ---

def test_tools_registered_only_when_configured(tmp_path):
    h, _ = home()
    tools = build_tools(None, NS(available=False), lambda t: None,
                        reminders=skills.Reminders(tmp_path / "r.json"),
                        lists=skills.Lists(tmp_path / "l.json"), home=h)
    assert {"allumer", "eteindre", "ouvrir", "verrouiller", "etat_maison"} <= set(tools)
    # pas d'outils domotique si non configuré
    plain = build_tools(None, NS(available=False), lambda t: None,
                        reminders=skills.Reminders(tmp_path / "r2.json"),
                        lists=skills.Lists(tmp_path / "l2.json"), home=SmartHome("", ""))
    assert "allumer" not in plain


def test_light_needs_no_confirmation_but_lock_and_cover_do():
    h, _ = home()
    tools = {t.name: t for t in build_smarthome(h)}
    assert tools["allumer"].confirm is None
    assert tools["eteindre"].confirm is None
    assert "verrouiller" in tools["verrouiller"].confirm("entrée")
    assert "Porte du garage" in tools["ouvrir"].confirm("garage")  # nom réel résolu


def test_works_offline(monkeypatch):
    # La maison est sur le réseau local : elle marche même en mode hors ligne.
    monkeypatch.setattr(config, "OFFLINE", True)
    h, ha = home()
    assert "allumé" in h.turn_on("chambre").lower()
    assert ha.calls


def test_point_de_situation(monkeypatch):
    import config
    etats = [
        {"entity_id": "sensor.frigate_jardin_person", "state": "1",
         "attributes": {"friendly_name": "Détection jardin"}},
        {"entity_id": "sensor.drone_batterie", "state": "80",
         "attributes": {"friendly_name": "Batterie drone", "unit_of_measurement": "%"}},
    ]
    h, _ = home(etats)
    monkeypatch.setattr(config, "TELEMETRIE", ("sensor.frigate_jardin_person", "sensor.drone_batterie"))
    out = h.point_de_situation()
    assert "Détection jardin" in out and "Batterie drone" in out
    # Rien configuré -> message clair, aucune invention
    monkeypatch.setattr(config, "TELEMETRIE", ())
    assert "Aucun capteur" in h.point_de_situation()
