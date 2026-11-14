"""Kill-switch visuel pour robot tondeuse — une MARGE de sécurité, pas le gardien unique.

Les caméras (Frigate) voient une personne ou un animal entrer dans la zone de tonte :
Jarvis envoie un ARRÊT d'urgence par MQTT, la tondeuse coupe ses lames et se fige. Elle ne
reprend qu'une fois le périmètre dégagé assez longtemps (ou sur ta confirmation).

DEUX LIGNES DE SÉCURITÉ, dites franchement :
- L'ARRÊT est autonome et immédiat (direction sûre). La REPRISE est prudente : jamais sur
  une seule image « vide » (un enfant accroupi n'est pas détecté) — il faut un dégagement
  DURABLE, et tu peux exiger une confirmation.
- Ce n'est PAS fail-safe : si la caméra/MQTT/Jarvis tombe, aucun arrêt n'est envoyé. La
  sécurité propre de la tondeuse (arrêt des lames au soulèvement, pare-chocs) et ta
  surveillance restent PRIMORDIALES. Ceci est une marge en plus.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

log = logging.getLogger("jarvis.tondeuse")


def analyser_frigate(charge: bytes, zones: tuple, camera: str, labels: tuple) -> "dict | None":
    """Vrai si un objet surveillé (personne/animal) est dans la zone de tonte."""
    try:
        data = json.loads(charge.decode("utf-8", "ignore"))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None
    if not isinstance(data, dict) or data.get("type") == "end":
        return None
    after = data.get("after") or data.get("before") or {}
    if after.get("label") not in labels:
        return None
    if camera and after.get("camera") != camera:
        return None
    dans = set(after.get("current_zones") or [])
    if zones and not (dans & set(zones)):
        return None
    return {"label": after.get("label"), "camera": after.get("camera", "")}


class MowerGuard:
    def __init__(self, publier: "Callable | None", notify: Callable[[str], None], store,
                 settings: "dict | None" = None, horloge: "Callable[[], float]" = time.monotonic,
                 arreter: "Callable | None" = None, reprendre: "Callable | None" = None,
                 lire_etat: "Callable | None" = None):
        self.publier = publier          # publier(topic, charge) -> None (backend MQTT)
        self._arreter = arreter         # backend Home Assistant : commandes injectées
        self._reprendre = reprendre
        self._lire_etat = lire_etat     # backend HA : état réel (mowing/paused/erreur, batterie)
        self.notify = notify
        self.store = store
        self.s = settings or {}
        self.horloge = horloge
        self._stoppe_par_garde = False
        self._dernier_danger = -1e18
        self.store.data.setdefault("arme", False)

    # --- Armement ---------------------------------------------------------------

    @property
    def arme(self) -> bool:
        return bool(self.store.data.get("arme"))

    def armer(self) -> str:
        self.store.data["arme"] = True
        self.store.save()
        return "🛡️ Kill-switch tondeuse armé. Je coupe les lames si quelqu'un approche."

    def desarmer(self) -> str:
        self.store.data["arme"] = False
        self.store.save()
        return "Kill-switch tondeuse désarmé (la tondeuse garde ses propres sécurités)."

    def etat(self) -> str:
        if not self.arme:
            base = "Kill-switch tondeuse désarmé."
        elif self._stoppe_par_garde:
            base = "Tondeuse à l'arrêt (intrus détecté)."
        else:
            base = "Kill-switch armé, tonte en cours."
        reel = self._lire_etat() if self._lire_etat else ""
        return base + reel

    # --- Réaction ---------------------------------------------------------------

    def _stop(self) -> None:
        if self._arreter is not None:
            self._arreter()
        else:
            self.publier(self.s.get("topic", "mower/command"), self.s.get("stop", "stop"))

    def _start(self) -> None:
        if self._reprendre is not None:
            self._reprendre()
        else:
            self.publier(self.s.get("topic", "mower/command"), self.s.get("start", "start"))

    def sur_detection(self, info: "dict | None" = None) -> dict:
        """Objet détecté dans la zone de tonte : ARRÊT immédiat (si armé)."""
        if not self.arme:
            return {}
        self._dernier_danger = self.horloge()
        if not self._stoppe_par_garde:
            try:
                self._stop()
            except Exception:
                log.exception("arrêt tondeuse")
                self.notify("⚠️ Je n'ai pas pu arrêter la tondeuse — vérifiez !")
                return {"erreur": True}
            self._stoppe_par_garde = True
            quoi = (info or {}).get("label", "quelqu'un")
            self.notify(f"🚨 {quoi} sur la zone de tonte — lames coupées, tondeuse immobilisée.")
        return {"arret": True}

    def tic(self) -> "str | None":
        """Appelé régulièrement : reprise si le périmètre est dégagé DEPUIS ASSEZ LONGTEMPS."""
        if not (self.arme and self._stoppe_par_garde):
            return None
        if not self.s.get("reprise_auto", True):
            return None     # reprise manuelle : on attend le propriétaire
        if self.horloge() - self._dernier_danger >= float(self.s.get("reprise_delai", 60)):
            try:
                self._start()
            except Exception:
                log.exception("reprise tondeuse")
                return None
            self._stoppe_par_garde = False
            self.notify("✅ Périmètre dégagé : la tondeuse reprend sa tonte.")
            return "reprise"
        return None

    # --- Commandes manuelles ----------------------------------------------------

    def arreter_maintenant(self) -> str:
        try:
            self._stop()
        except Exception:
            return "Je n'ai pas pu joindre la tondeuse."
        self._stoppe_par_garde = True
        self._dernier_danger = self.horloge()
        return "Tondeuse arrêtée."

    def reprendre_maintenant(self) -> str:
        try:
            self._start()
        except Exception:
            return "Je n'ai pas pu joindre la tondeuse."
        self._stoppe_par_garde = False
        return "Tondeuse relancée."


def _tools_from_guard(guard: MowerGuard) -> list:
    from tools import Tool

    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="armer_tondeuse", description="Arme le kill-switch visuel de la tondeuse.",
             parameters=vide, run=lambda: guard.armer()),
        Tool(name="desarmer_tondeuse", description="Désarme le kill-switch de la tondeuse.",
             parameters=vide, run=lambda: guard.desarmer()),
        Tool(name="arreter_tondeuse", description="Arrête la tondeuse tout de suite (coupe les lames).",
             parameters=vide, run=lambda: guard.arreter_maintenant()),
        Tool(name="reprendre_tondeuse", description="Relance la tondeuse (après vérification du périmètre).",
             parameters=vide, run=lambda: guard.reprendre_maintenant()),
        Tool(name="etat_tondeuse", description="Dit l'état du kill-switch et de la tondeuse.",
             parameters=vide, run=lambda: guard.etat()),
    ]


# --- Veille (MQTT Frigate + boucle de reprise) --------------------------------------

_GUARD: "MowerGuard | None" = None


_ETATS_FR = {"mowing": "en train de tondre", "paused": "en pause", "docked": "à la base",
             "returning": "retour à la base", "error": "⚠️ en erreur"}


def _commandes_ha(home, entite: str):
    """Backend Home Assistant : pause (arrêt sur place, lames coupées) / reprise."""
    def arreter():
        home.call("lawn_mower", "pause", entite)
    def reprendre():
        home.call("lawn_mower", "start_mowing", entite)
    return arreter, reprendre


def _lecture_ha(home, entite: str, batterie: str):
    """Lit l'état réel de la tondeuse (mowing/paused/erreur) + batterie, depuis Home Assistant."""
    def lire() -> str:
        try:
            etats = {e["entity_id"]: e for e in home.states()}
        except Exception:
            return ""
        m = etats.get(entite)
        if not m:
            return ""
        reel = _ETATS_FR.get(str(m.get("state", "")).lower(), m.get("state", "?"))
        bat = ""
        if batterie and batterie in etats and etats[batterie].get("state") not in (None, "unknown"):
            bat = f", batterie {etats[batterie]['state']} %"
        return f" (réel : {reel}{bat})"
    return lire


def guard(notify, home=None) -> "MowerGuard | None":
    global _GUARD
    import config
    from skills import JsonStore

    if not (config.MOWER and config.MOWER_ZONES):
        return None
    if _GUARD is None:
        store = JsonStore(config.MOWER_FILE, {})
        settings = config.tondeuse_settings()
        if config.MOWER_BACKEND == "ha" and home is not None and config.MOWER_ENTITE:
            arreter, reprendre = _commandes_ha(home, config.MOWER_ENTITE)
            lire = _lecture_ha(home, config.MOWER_ENTITE, config.MOWER_BATTERIE)
            _GUARD = MowerGuard(None, notify, store, settings, arreter=arreter,
                                reprendre=reprendre, lire_etat=lire)
        else:
            _GUARD = MowerGuard(_publier_mqtt, notify, store, settings)
    return _GUARD


def build_mower_tools(notify, home=None) -> list:
    g = guard(notify, home)
    return _tools_from_guard(g) if g is not None else []


def _publier_mqtt(topic: str, charge: str) -> None:
    import paho.mqtt.publish as publish

    import config
    auth = {"username": config.MQTT_USER, "password": config.MQTT_PASS} if config.MQTT_USER else None
    publish.single(topic, charge, hostname=config.MQTT_HOST, port=config.MQTT_PORT, auth=auth)


class MowerWatcher:
    def __init__(self, guard: MowerGuard, zones, camera, labels, host="localhost", port=1883,
                 topic="frigate/events", username="", password="", client=None, tic_s: float = 5.0):
        self.guard = guard
        self.zones, self.camera, self.labels = zones, camera, labels
        self.host, self.port, self.topic = host, port, topic
        self.username, self.password = username, password
        self._client = client
        self.tic_s = tic_s
        self._halt = threading.Event()

    def traiter(self, charge: bytes) -> None:
        info = analyser_frigate(charge, self.zones, self.camera, self.labels)
        if info is not None:
            try:
                self.guard.sur_detection(info)
            except Exception:
                log.exception("réaction tondeuse")

    def _boucle_reprise(self) -> None:
        while not self._halt.wait(self.tic_s):
            try:
                self.guard.tic()
            except Exception:
                log.exception("reprise tondeuse")

    def demarrer(self) -> dict:
        if self._client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                return {"statut": "erreur", "message": "paho-mqtt manquant"}
            self._client = mqtt.Client()
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_message = lambda c, u, msg: self.traiter(msg.payload)
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.subscribe(self.topic)
        except OSError as exc:
            return {"statut": "erreur", "message": f"MQTT injoignable : {exc}"}
        threading.Thread(target=self._client.loop_forever, name="jarvis-tondeuse", daemon=True).start()
        threading.Thread(target=self._boucle_reprise, name="jarvis-tondeuse-reprise", daemon=True).start()
        return {"statut": "succès", "message": "Kill-switch tondeuse actif"}


def make_mower_watcher(notify, home=None) -> "MowerWatcher | None":
    import config

    g = guard(notify, home)
    if g is None:
        return None
    return MowerWatcher(g, config.MOWER_ZONES, config.MOWER_CAMERA, config.MOWER_LABELS,
                        host=config.MQTT_HOST, port=config.MQTT_PORT,
                        username=config.MQTT_USER, password=config.MQTT_PASS)
