"""Tests du pilotage et de la vision du drone, avec le simulateur (aucun matériel)."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import skills  # noqa: E402
from drone import AnafiController, DronePilot, MavlinkController, SimDrone, build_drone_tools  # noqa: E402
from tools import build_tools  # noqa: E402


def pilot(describe=None):
    return DronePilot(SimDrone(), describe=describe)


# --- Sécurité et ordre des opérations ---

def test_cannot_move_before_takeoff():
    p = pilot()
    assert "décolle" in p.move(forward=2).lower()
    assert "n'est pas en vol" in p.rotate(90).lower() or "décolle" in p.rotate(90).lower()


def test_takeoff_then_move_then_land():
    p = pilot()
    assert "Décollage" in p.takeoff()
    assert p.c.flying is True
    msg = p.move(forward=2, up=1)
    assert "avance de 2 m" in msg and "monte de 1 m" in msg
    assert p.c.pos[0] == 2 and p.c.pos[2] > 1
    assert "Atterrissage" in p.land()
    assert p.c.flying is False


def test_double_takeoff_and_land_on_ground():
    p = pilot()
    p.takeoff()
    assert "déjà en vol" in p.takeoff()
    p.land()
    assert "déjà au sol" in p.land()


def test_move_is_clamped_to_step_limit():
    p = pilot()                     # limite par défaut : 20 m par commande
    p.takeoff()
    p.move(forward=100)
    assert p.c.pos[0] == 20.0


def test_altitude_ceiling_is_enforced():
    # Plafond réglé à 10 m : le drone ne doit jamais le dépasser, même sur plusieurs ordres.
    p = DronePilot(SimDrone(), alt_max=10.0, step_max=20.0)
    p.takeoff()                     # ~1.2 m
    msg = p.move(up=20)             # demande +20 m
    assert p.c.pos[2] == 10.0 and "plafond de 10 m" in msg
    p.move(up=20)                   # déjà au plafond : ne monte plus
    assert p.c.pos[2] == 10.0
    p.move(up=-4)                   # redescendre reste possible
    assert p.c.pos[2] == 6.0


def test_custom_step_limit():
    p = DronePilot(SimDrone(), step_max=50.0, alt_max=120.0)
    p.takeoff()
    p.move(forward=40)
    assert p.c.pos[0] == 40.0


def test_rotate_clamped():
    p = pilot()
    p.takeoff()
    p.rotate(999)
    assert p.c.yaw == 180           # borné à 180°


def test_emergency_always_cuts_motors():
    p = pilot()
    p.takeoff()
    assert "urgence" in p.emergency().lower()
    assert p.c.flying is False


def test_bad_values_do_not_crash():
    p = pilot()
    p.takeoff()
    assert "ne bouge pas" in p.move(forward="beaucoup")  # valeur illisible -> 0


# --- Connexion / pannes ---

def test_connection_failure_is_friendly():
    class Dead(SimDrone):
        def connect(self):
            return False

    assert "connecter au drone" in DronePilot(Dead()).takeoff()


def test_connection_exception_is_caught():
    class Boom(SimDrone):
        def connect(self):
            raise OSError("wifi")

    assert "joindre le drone" in DronePilot(Boom()).takeoff()


# --- Vision ---

def test_look_needs_flight_and_frame():
    p = pilot(describe=lambda f: "Je vois un salon.")
    assert "décolle" in p.look().lower()
    p.takeoff()
    assert p.look() == "Je vois un salon."


def test_look_passes_frame_to_describer():
    seen = {}
    p = pilot(describe=lambda f: seen.setdefault("frame", f) or "ok")
    p.takeoff()
    p.look()
    assert seen["frame"].startswith(b"\xff\xd8\xff")   # une image JPEG


def test_look_without_vision_configured():
    p = pilot(describe=None)
    p.takeoff()
    assert "pas configurée" in p.look()


def test_look_handles_vision_error():
    def boom(frame):
        raise RuntimeError("api")

    p = pilot(describe=boom)
    p.takeoff()
    assert "n'arrive pas à analyser" in p.look()


def test_status():
    p = pilot()
    assert "pas connecté" in p.status()
    p.takeoff()
    s = p.status()
    assert "en vol" in s and "batterie" in s


# --- Vraie classe ANAFI : pas de vol sans le SDK, mais pas de plantage ---

def test_anafi_without_sdk_is_graceful():
    # Olympe n'est pas installé ici : la connexion doit échouer proprement.
    assert "joindre le drone" in DronePilot(AnafiController()).takeoff()


# --- Outils exposés à Jarvis ---

def test_tools_registered_and_takeoff_confirms(tmp_path):
    p = pilot()
    tools = {t.name: t for t in build_drone_tools(p)}
    assert {"drone_decoller", "drone_atterrir", "drone_urgence", "drone_voir", "drone_etat"} <= set(tools)
    assert "DÉCOLLER" in tools["drone_decoller"].confirm()
    assert tools["drone_atterrir"].confirm is None    # atterrir : jamais bloqué
    assert tools["drone_urgence"].confirm is None      # urgence : jamais bloquée


def test_drone_tools_in_build_tools(tmp_path):
    p = pilot()
    tools = build_tools(None, NS(available=False), lambda s: None,
                        reminders=skills.Reminders(tmp_path / "r.json"),
                        lists=skills.Lists(tmp_path / "l.json"), drone=p)
    assert "drone_decoller" in tools
    none = build_tools(None, NS(available=False), lambda s: None,
                       reminders=skills.Reminders(tmp_path / "r2.json"),
                       lists=skills.Lists(tmp_path / "l2.json"))
    assert "drone_decoller" not in none


def test_gemini_describe_image_mock():
    from claude_bridge import GeminiBackend

    captured = {}

    def request(body):
        captured.update(body)
        return {"candidates": [{"content": {"parts": [{"text": "Je vois un jardin avec un arbre."}]}}]}

    out = GeminiBackend(request=request).describe_image(b"\xff\xd8\xff fake jpeg")
    assert out == "Je vois un jardin avec un arbre."
    part0 = captured["contents"][0]["parts"][0]
    assert "inline_data" in part0 and part0["inline_data"]["mime_type"] == "image/jpeg"


# --- Drone DIY via MAVLink (ArduPilot/PX4) ---

class RecordingMavlink(MavlinkController):
    """MavlinkController dont les appels bas niveau sont enregistrés (pas de pymavlink)."""

    def __init__(self):
        super().__init__(connection=object())  # connexion déjà « ouverte »
        self.events = []

    def _set_mode(self, name): self.events.append(("mode", name))
    def _arm(self, on): self.events.append(("arm", on))
    def _takeoff(self, alt): self.events.append(("takeoff", alt))
    def _move_ned(self, n, e, d): self.events.append(("move", n, e, d))
    def _yaw(self, deg): self.events.append(("yaw", deg))
    def _telemetry(self): return {"vole": True, "batterie": 80}


def test_mavlink_pilot_full_sequence():

    ctrl = RecordingMavlink()
    p = DronePilot(ctrl)
    assert "Décollage" in p.takeoff()
    assert ("mode", "GUIDED") in ctrl.events     # connexion → mode piloté
    assert ("arm", True) in ctrl.events and any(e[0] == "takeoff" for e in ctrl.events)
    p.move(forward=2, up=1)
    # haut=1 doit devenir « bas = -1 » en MAVLink
    assert ("move", 2.0, 0.0, -1.0) in ctrl.events
    p.rotate(90)
    assert ("yaw", 90.0) in ctrl.events
    assert "Atterrissage" in p.land() and ("mode", "LAND") in ctrl.events


def test_mavlink_emergency_returns_home():
    ctrl = RecordingMavlink()
    p = DronePilot(ctrl)
    p.takeoff()
    assert "urgence" in p.emergency().lower()
    assert ("mode", "RTL") in ctrl.events        # urgence = retour maison, réflexe sûr


def test_mavlink_without_pymavlink_is_graceful():
    # pymavlink non installé ici : connect() doit échouer proprement, pas planter.
    assert "joindre le drone" in DronePilot(MavlinkController(url="udp:127.0.0.1:14550")).takeoff()


def test_simulator_has_no_ceiling():
    # En simulateur, aucune limite : c'est virtuel, sans danger.
    p = DronePilot(SimDrone(), alt_max=float("inf"), step_max=float("inf"))
    p.takeoff()
    msg = p.move(up=1000)
    assert p.c.pos[2] > 1000 and "plafond" not in msg
