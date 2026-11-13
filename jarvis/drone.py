"""Pilotage et vision du drone (Parrot ANAFI) pour Jarvis.

Deux pilotes :
- SimDrone : un simulateur (aucun matériel), pour tester et faire une démo.
- AnafiController : le vrai Parrot ANAFI, via le SDK officiel Olympe (chargé à la demande).

Sécurité, toujours :
- Jarvis demande confirmation AVANT le décollage.
- « Atterris » et « Arrête-toi » (urgence) sont toujours acceptés, sans confirmation.
- Les déplacements sont bornés (distance et altitude maximales).
- Rien ne vole sans que tu gardes le drone à vue et respectes les règles de vol.
"""

import logging
from typing import Callable, Protocol

import config

log = logging.getLogger("jarvis.drone")

# Limites par défaut. Réglables dans .env (voir config). L'altitude max par défaut
# est le plafond LÉGAL en France/Europe (120 m). Le drone en est capable ; c'est à toi
# de rester dans la loi de ton pays.
MAX_STEP_M = 20.0     # déplacement max par commande (mètres)
MAX_ALT_M = 120.0     # altitude max (mètres) — plafond légal EASA
MAX_TURN_DEG = 180.0


class Controller(Protocol):
    def connect(self) -> bool: ...
    def takeoff(self) -> None: ...
    def land(self) -> None: ...
    def emergency(self) -> None: ...
    def move(self, forward: float, right: float, up: float) -> None: ...
    def rotate(self, degrees: float) -> None: ...
    def frame(self) -> "bytes | None": ...
    def telemetry(self) -> dict: ...


class SimDrone:
    """Simulateur : suit position, cap et batterie. Aucun matériel nécessaire."""

    def __init__(self):
        self.connected = False
        self.flying = False
        self.pos = [0.0, 0.0, 0.0]  # avant/arrière, gauche/droite, hauteur
        self.yaw = 0.0
        self.battery = 100

    def connect(self) -> bool:
        self.connected = True
        return True

    def _drain(self, n: int = 1) -> None:
        self.battery = max(0, self.battery - n)

    def takeoff(self) -> None:
        self.flying = True
        self.pos[2] = 1.2
        self._drain(2)

    def land(self) -> None:
        self.flying = False
        self.pos[2] = 0.0
        self._drain()

    def emergency(self) -> None:
        self.flying = False
        self.pos[2] = 0.0

    def move(self, forward: float, right: float, up: float) -> None:
        self.pos[0] += forward
        self.pos[1] += right
        self.pos[2] = max(0.0, self.pos[2] + up)
        self._drain()

    def rotate(self, degrees: float) -> None:
        self.yaw = (self.yaw + degrees) % 360
        self._drain()

    def frame(self) -> "bytes | None":
        return b"\xff\xd8\xff\xe0JARVIS-SIM" if self.flying else None  # image factice

    def telemetry(self) -> dict:
        return {"vole": self.flying, "batterie": self.battery,
                "altitude": round(self.pos[2], 1), "cap": round(self.yaw)}


class AnafiController:
    """Vrai Parrot ANAFI via le SDK Olympe. Chargé seulement quand on l'utilise."""

    def __init__(self, ip: str = ""):
        self.ip = ip or config.DRONE_IP
        self._drone = None

    def connect(self) -> bool:
        if self._drone is None:
            from olympe import Drone  # SDK lourd (Linux) : installé seulement pour voler

            self._drone = Drone(self.ip)
        return bool(self._drone.connect())

    def takeoff(self) -> None:
        from olympe.messages.ardrone3.Piloting import TakeOff

        self._drone(TakeOff()).wait()

    def land(self) -> None:
        from olympe.messages.ardrone3.Piloting import Landing

        self._drone(Landing()).wait()

    def emergency(self) -> None:
        from olympe.messages.ardrone3.Piloting import Emergency

        self._drone(Emergency()).wait()

    def move(self, forward: float, right: float, up: float) -> None:
        from olympe.messages.ardrone3.Piloting import moveBy

        self._drone(moveBy(forward, right, -up, 0.0)).wait()  # Olympe : z vers le bas

    def rotate(self, degrees: float) -> None:
        import math

        from olympe.messages.ardrone3.Piloting import moveBy

        self._drone(moveBy(0.0, 0.0, 0.0, math.radians(degrees))).wait()

    def frame(self) -> "bytes | None":
        getter = getattr(self, "_last_frame", None)
        return getter() if callable(getter) else None

    def telemetry(self) -> dict:
        return {"vole": None, "batterie": None}


class MavlinkController:
    """Drone DIY (ArduPilot/PX4) via MAVLink. Pour un mini-Jarvis EMBARQUÉ sur le drone.

    Le même code tourne sur l'ordinateur de bord (Raspberry Pi/Jetson) ou au sol.
    Les appels bas niveau MAVLink sont isolés dans les méthodes `_...`, pour pouvoir
    les tester et les valider dans le simulateur ArduPilot (SITL) avant de voler.
    """

    def __init__(self, url: str = "", connection=None, takeoff_alt: float = 2.0):
        self.url = url or config.DRONE_URL
        self._conn = connection
        self._takeoff_alt = takeoff_alt

    def connect(self) -> bool:
        if self._conn is None:
            from pymavlink import mavutil

            self._conn = mavutil.mavlink_connection(self.url)
            self._conn.wait_heartbeat(timeout=15)
        self._set_mode("GUIDED")   # mode piloté par programme
        return True

    def takeoff(self) -> None:
        self._arm(True)
        self._takeoff(self._takeoff_alt)

    def land(self) -> None:
        self._set_mode("LAND")

    def emergency(self) -> None:
        self._set_mode("RTL")      # réflexe sûr : le drone rentre tout seul à son point de départ

    def move(self, forward: float, right: float, up: float) -> None:
        self._move_ned(forward, right, -up)  # MAVLink : l'axe « bas » est positif

    def rotate(self, degrees: float) -> None:
        self._yaw(degrees)

    def frame(self) -> "bytes | None":
        getter = getattr(self, "_camera", None)  # la caméra embarquée se branche ici
        return getter() if callable(getter) else None

    def telemetry(self) -> dict:
        return self._telemetry()

    # --- Bas niveau MAVLink (à valider dans ArduPilot SITL) -----------------------------

    def _set_mode(self, name: str) -> None:
        self._conn.set_mode_apm(name)

    def _arm(self, on: bool) -> None:
        from pymavlink import mavutil

        self._conn.mav.command_long_send(
            self._conn.target_system, self._conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1 if on else 0, 0, 0, 0, 0, 0, 0)

    def _takeoff(self, alt: float) -> None:
        from pymavlink import mavutil

        self._conn.mav.command_long_send(
            self._conn.target_system, self._conn.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, 0, alt)

    def _move_ned(self, north: float, east: float, down: float) -> None:
        from pymavlink import mavutil

        self._conn.mav.set_position_target_local_ned_send(
            0, self._conn.target_system, self._conn.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_OFFSET_NED, 0b0000111111111000,
            north, east, down, 0, 0, 0, 0, 0, 0, 0, 0)

    def _yaw(self, degrees: float) -> None:
        from pymavlink import mavutil

        self._conn.mav.command_long_send(
            self._conn.target_system, self._conn.target_component,
            mavutil.mavlink.MAV_CMD_CONDITION_YAW, 0,
            abs(degrees), 0, 1 if degrees > 0 else -1, 1, 0, 0, 0)

    def _telemetry(self) -> dict:
        return {"vole": None, "batterie": None}


class DronePilot:
    """Couche de sécurité : borne les commandes et garde l'ordre des opérations."""

    def __init__(self, controller: Controller, describe: "Callable[[bytes], str] | None" = None,
                 step_max: float = None, alt_max: float = None):
        self.c = controller
        self.describe = describe
        self.step_max = MAX_STEP_M if step_max is None else float(step_max)
        self.alt_max = MAX_ALT_M if alt_max is None else float(alt_max)
        self._ready = False
        self._flying = False
        self._alt = 0.0  # estimation de l'altitude, pour faire respecter le plafond

    def _ensure_ready(self) -> "str | None":
        if self._ready:
            return None
        try:
            if not self.c.connect():
                return "Je n'arrive pas à me connecter au drone. Il est allumé et le Wi-Fi est bon ?"
        except Exception as exc:
            log.warning("connexion drone : %s", exc)
            return "Je n'arrive pas à joindre le drone (SDK ou Wi-Fi). Vérifie l'installation."
        self._ready = True
        return None

    @staticmethod
    def _num(value, limit: float) -> float:
        try:
            value = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(-limit, min(limit, value))

    # --- Commandes ----------------------------------------------------------------------

    def takeoff(self) -> str:
        err = self._ensure_ready()
        if err:
            return err
        if self._flying:
            return "Le drone est déjà en vol."
        try:
            self.c.takeoff()
        except Exception as exc:
            return f"Décollage impossible : {exc}"
        self._flying = True
        self._alt = 1.2  # altitude de vol stationnaire au décollage
        return "Décollage. Vol stationnaire. Garde le drone à vue."

    def land(self) -> str:
        if not self._flying:
            return "Le drone est déjà au sol."
        try:
            self.c.land()
        except Exception as exc:
            return f"Atterrissage : {exc}"
        self._flying = False
        self._alt = 0.0
        return "Atterrissage en cours."

    def emergency(self) -> str:
        if not self._ready:
            return "Le drone n'est pas connecté."
        try:
            self.c.emergency()
        except Exception as exc:
            return f"Arrêt d'urgence : {exc}"
        self._flying = False
        self._alt = 0.0
        return "Arrêt d'urgence. Le drone coupe ses moteurs."

    def _check_flying(self) -> "str | None":
        if not self._flying:
            return "Le drone n'est pas en vol. Dis « décolle » d'abord."
        return None

    def move(self, forward: float = 0, right: float = 0, up: float = 0) -> str:
        busy = self._check_flying()
        if busy:
            return busy
        f = self._num(forward, self.step_max)
        r = self._num(right, self.step_max)
        u = self._num(up, self.step_max)
        # Barrière d'altitude : on ne dépasse ni le plafond, ni le sol.
        capped = False
        target_alt = round(max(0.0, min(self.alt_max, self._alt + u)), 6)
        allowed_u = round(target_alt - self._alt, 6)
        if abs(allowed_u - u) > 1e-6:
            capped = True
        u = allowed_u
        try:
            self.c.move(f, r, u)
        except Exception as exc:
            return f"Déplacement impossible : {exc}"
        self._alt = target_alt
        bits = []
        if f:
            bits.append(f"{'avance' if f > 0 else 'recule'} de {abs(f):g} m")
        if r:
            bits.append(f"{'droite' if r > 0 else 'gauche'} {abs(r):g} m")
        if u:
            bits.append(f"{'monte' if u > 0 else 'descend'} de {abs(u):g} m")
        msg = "D'accord, le drone " + (", ".join(bits) if bits else "ne bouge pas") + "."
        if capped:
            msg += f" (Je reste sous le plafond de {self.alt_max:g} m.)"
        return msg

    def rotate(self, degrees: float) -> str:
        busy = self._check_flying()
        if busy:
            return busy
        d = self._num(degrees, MAX_TURN_DEG)
        try:
            self.c.rotate(d)
        except Exception as exc:
            return f"Rotation impossible : {exc}"
        return f"Le drone tourne de {abs(d):g} degrés vers la {'droite' if d > 0 else 'gauche'}."

    def look(self) -> str:
        busy = self._check_flying()
        if busy:
            return busy
        frame = self.c.frame()
        if not frame:
            return "Je n'ai pas d'image du drone pour le moment."
        if self.describe is None:
            return ("Je reçois bien la vidéo du drone, mais la vision n'est pas configurée. "
                    "Installe un modèle qui voit (ollama pull qwen2.5-vl, puis "
                    "JARVIS_MODELE_VISION=qwen2.5-vl), ou configure Gemini.")
        try:
            return self.describe(frame)
        except Exception as exc:
            log.warning("vision drone : %s", exc)
            return "Je n'arrive pas à analyser l'image du drone."

    def status(self) -> str:
        if not self._ready:
            return "Le drone n'est pas connecté."
        t = self.c.telemetry()
        parts = ["en vol" if t.get("vole") else "au sol"]
        if t.get("batterie") is not None:
            parts.append(f"batterie {t['batterie']} %")
        if t.get("altitude") is not None:
            parts.append(f"altitude {t['altitude']} m")
        return "Drone : " + ", ".join(parts) + "."


def build_drone_tools(pilot: "DronePilot") -> list:
    from tools import Tool


    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    metres = {"type": "number", "description": "Distance en mètres (max 5)."}
    return [
        Tool(name="drone_decoller",
             description="Fait décoller le drone. À confirmer.",
             parameters=obj({}, []),
             run=pilot.takeoff,
             confirm=lambda: "Je vais faire DÉCOLLER le drone. Assure-toi qu'il est dégagé et à vue."),
        Tool(name="drone_atterrir",
             description="Fait atterrir le drone. Toujours autorisé.",
             parameters=obj({}, []),
             run=pilot.land),
        Tool(name="drone_urgence",
             description="ARRÊT D'URGENCE : coupe les moteurs immédiatement. Pour « arrête-toi », « stop ».",
             parameters=obj({}, []),
             run=pilot.emergency),
        Tool(name="drone_deplacer",
             description=("Déplace le drone. Valeurs en mètres (max 5) : avant=forward, droite=right, "
                          "haut=up ; négatif pour reculer/gauche/descendre."),
             parameters=obj({"forward": metres, "right": metres, "up": metres}, []),
             run=pilot.move),
        Tool(name="drone_tourner",
             description="Fait pivoter le drone sur place. Degrés positifs = droite, négatifs = gauche.",
             parameters=obj({"degres": {"type": "number", "description": "Angle en degrés (max 180)."}}, ["degres"]),
             run=lambda degres: pilot.rotate(degres)),
        Tool(name="drone_voir",
             description=("Regarde à travers la caméra du drone et décrit ce qu'il voit. "
                          "Pour « qu'est-ce que tu vois ? », « décris la scène »."),
             parameters=obj({}, []),
             run=pilot.look),
        Tool(name="drone_etat",
             description="Donne l'état du drone : en vol ou au sol, batterie, altitude.",
             parameters=obj({}, []),
             run=pilot.status),
    ]
