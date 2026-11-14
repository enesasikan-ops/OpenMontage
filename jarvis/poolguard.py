"""Surveillance piscine — alerte de sécurité, PAS un détecteur de noyade.

⚠️ À LIRE. Frigate (ou une caméra IP étanche) détecte « une personne dans la zone de la
piscine » — il ne détecte PAS une noyade, et ne garantit pas de distinguer un enfant qui
coule d'un enfant qui nage, d'un reflet ou d'une feuille. C'est une ALERTE de plus, qui
ne remplace JAMAIS une barrière, une couverture, une alarme de porte, des cours de
natation et, surtout, ta surveillance.

Ce que fait ce module quand une personne est détectée dans la zone piscine (et que tu as
armé la surveillance) :
1. déclenche une ALARME hurlante dans la maison (bénin en cas de fausse alerte : tu vas
   voir — c'est exactement ce qu'on veut) ;
2. allume les lumières ;
3. (option) déverrouille les baies vitrées pour que tu coures plus vite ;
4. t'alerte aussitôt, à voix haute ;
5. si le mode URGENCE est armé : lance un DÉCOMPTE ANNULABLE puis alerte tes contacts
   d'urgence. Jarvis n'appelle jamais les secours publics tout seul sur une supposition
   (faux positifs → fausses alertes aux secours, c'est dangereux et illégal) : il te
   hurle d'appeler le 112 et relaie à TES contacts configurés. Tu dis « annule » pour une
   fausse alerte.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

log = logging.getLogger("jarvis.piscine")

# Message par défaut : VRAI (une détection, pas une certitude de noyade).
MESSAGE_DEFAUT = ("Possible chute dans la piscine détectée. Rendez-vous immédiatement "
                  "au bassin. Si quelqu'un est dans l'eau, appelez le 112.")


def _service(home, service: str, entity_id, **data) -> None:
    domaine, _, nom = (service or "").partition(".")
    if domaine and nom and entity_id:
        home.call(domaine, nom, entity_id, **data)


def analyser_frigate(charge: bytes, zones: tuple, camera: str = "") -> "dict | None":
    """Lit un évènement Frigate (topic frigate/events). Renvoie l'info si une PERSONNE
    est dans une zone de la piscine, sinon None. (Détection de personne, pas de noyade.)"""
    try:
        data = json.loads(charge.decode("utf-8", "ignore"))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return None
    if not isinstance(data, dict) or data.get("type") == "end":
        return None
    after = data.get("after") or data.get("before") or {}
    if after.get("label") != "person":
        return None
    if camera and after.get("camera") != camera:
        return None
    dans = set(after.get("current_zones") or [])
    if zones and not (dans & set(zones)):
        return None
    return {"camera": after.get("camera", ""), "zones": sorted(dans)}


class PoolGuard:
    def __init__(self, home, notify: Callable[[str], None], store,
                 settings: "dict | None" = None, escalader: "Callable | None" = None,
                 evidence=None, horloge: "Callable[[], float]" = time.monotonic,
                 minuteur: "Callable | None" = None):
        self.home = home
        self.notify = notify
        self.store = store
        self.s = settings or {}
        self.escalader = escalader            # escalader(message) : alerte les contacts d'urgence
        self.evidence = evidence
        self.horloge = horloge
        self._minuteur = minuteur or (lambda delai, fn: threading.Timer(delai, fn))
        self._timer = None
        self._derniere = -1e18
        self.store.data.setdefault("urgence", False)

    # --- Armement du mode Urgence -------------------------------------------------

    @property
    def urgence_armee(self) -> bool:
        return bool(self.store.data.get("urgence"))

    def armer_urgence(self) -> str:
        self.store.data["urgence"] = True
        self.store.save()
        return ("🚨 Mode Urgence piscine ARMÉ. En cas de détection, j'alerterai vos contacts "
                "d'urgence après un décompte. (Ceci ne remplace pas votre surveillance.)")

    def desarmer_urgence(self) -> str:
        self.store.data["urgence"] = False
        self.store.save()
        self._annuler_timer()
        return "Mode Urgence piscine désarmé."

    def etat(self) -> str:
        return ("Mode Urgence piscine armé." if self.urgence_armee
                else "Mode Urgence piscine désarmé (alarme et lumières restent actives sur détection).")

    # --- Réaction à une détection -------------------------------------------------

    def sur_detection(self, info: "dict | None" = None) -> dict:
        maintenant = self.horloge()
        cooldown = float(self.s.get("cooldown", 20))
        if maintenant - self._derniere < cooldown:    # évite de re-hurler en continu
            return {"ignore": "cooldown"}
        self._derniere = maintenant

        faites: list = []
        self._sirene(faites)
        self._lumieres(faites)
        self._deverrouiller_baies(faites)
        self._annonce_vocale(faites)
        zone = f" ({info.get('camera')})" if info and info.get("camera") else ""
        self.notify(f"🚨 PISCINE{zone} : personne détectée dans l'eau. FONCEZ au bassin. "
                    + (f"Réaction : {', '.join(faites)}." if faites else ""))
        self._consigner(f"détection piscine{zone}")

        escalade = False
        if self.urgence_armee and self.escalader is not None:
            self._programmer_escalade()
            escalade = True
        return {"faites": faites, "escalade_programmee": escalade}

    def annuler(self) -> str:
        """Fausse alerte : annule l'escalade vers les secours (l'alarme, coupe-la à la main)."""
        if self._annuler_timer():
            self._consigner("escalade piscine annulée par le propriétaire")
            return "Escalade annulée. (Coupez l'alarme quand vous voulez.)"
        return "Il n'y a pas d'escalade en cours."

    def couper_alarme(self) -> str:
        sirene = self.s.get("sirene")
        if sirene:
            service = self.s.get("sirene_service", "siren.turn_on").replace("turn_on", "turn_off")
            self._sur(lambda: _service(self.home, service, sirene), "sirène coupée", [])
        return "Alarme coupée."

    # --- Effecteurs ---------------------------------------------------------------

    def _sirene(self, faites: list) -> None:
        sirene = self.s.get("sirene")
        if sirene:
            self._sur(lambda: _service(self.home, self.s.get("sirene_service", "siren.turn_on"),
                                       sirene), "alarme", faites)

    def _lumieres(self, faites: list) -> None:
        lum = self.s.get("lumieres") or []
        if lum:
            self._sur(lambda: self.home.call("light", "turn_on", list(lum)), "lumières", faites)

    def _deverrouiller_baies(self, faites: list) -> None:
        baies = self.s.get("baies") or []
        if baies:
            self._sur(lambda: self.home.call("lock", "unlock", list(baies)),
                      "baies déverrouillées", faites)

    def _annonce_vocale(self, faites: list) -> None:
        hp = self.s.get("haut_parleur")
        if hp:
            msg = self.s.get("message") or MESSAGE_DEFAUT
            self._sur(lambda: _service(self.home, self.s.get("tts_service", "tts.google_translate_say"),
                                       hp, message=msg), "annonce vocale", faites)

    # --- Escalade (décompte annulable) --------------------------------------------

    def _programmer_escalade(self) -> None:
        self._annuler_timer()
        delai = float(self.s.get("urgence_delai", 15))
        self.notify(f"⏱️ J'alerte vos contacts d'urgence dans {int(delai)} s. Dites « annule » "
                    "si c'est une fausse alerte.")
        self._timer = self._minuteur(delai, self._escalader_maintenant)
        self._timer.start()

    def _escalader_maintenant(self) -> None:
        self._timer = None
        message = MESSAGE_DEFAUT
        try:
            self.escalader(message)
            self._consigner("escalade piscine : contacts d'urgence alertés")
            self.notify("📞 Contacts d'urgence alertés. Appelez le 112 si ce n'est pas déjà fait.")
        except Exception:
            log.exception("escalade piscine")
            self.notify("⚠️ Échec de l'alerte aux contacts d'urgence — APPELEZ LE 112 VOUS-MÊME.")

    def _annuler_timer(self) -> bool:
        if self._timer is not None:
            try:
                self._timer.cancel()
            except Exception:
                pass
            self._timer = None
            return True
        return False

    # --- Utilitaires --------------------------------------------------------------

    def _consigner(self, texte: str) -> None:
        if self.evidence is not None:
            try:
                self.evidence.consigner(texte)
            except Exception:
                log.exception("journal de preuves piscine")

    @staticmethod
    def _sur(action: Callable, libelle: str, faites: list) -> None:
        try:
            action()
            faites.append(libelle)
        except Exception:
            log.exception("piscine : %s", libelle)


def _tools_from_guard(guard: PoolGuard) -> list:
    from tools import Tool

    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="armer_urgence_piscine",
             description="Arme le mode Urgence piscine (alerte des contacts d'urgence sur détection).",
             parameters=vide, run=lambda: guard.armer_urgence()),
        Tool(name="desarmer_urgence_piscine",
             description="Désarme le mode Urgence piscine.",
             parameters=vide, run=lambda: guard.desarmer_urgence()),
        Tool(name="annuler_alerte_piscine",
             description="Annule l'escalade vers les secours (fausse alerte piscine).",
             parameters=vide, run=lambda: guard.annuler()),
        Tool(name="couper_alarme_piscine",
             description="Coupe la sirène de la piscine.",
             parameters=vide, run=lambda: guard.couper_alarme()),
        Tool(name="etat_urgence_piscine",
             description="Dit si le mode Urgence piscine est armé.",
             parameters=vide, run=lambda: guard.etat()),
    ]


# --- Escalade vers les contacts d'urgence -------------------------------------------


def make_escalader(notify: Callable[[str], None], webhook: str = "",
                   poster: "Callable | None" = None) -> Callable:
    """Renvoie la fonction d'escalade. Elle N'APPELLE PAS le 112 automatiquement : elle
    alerte le propriétaire et relaie à un service d'alerte CONFIGURÉ (ton téléphone, un
    gardien), si tu en as branché un. Composer le 112 reste une décision humaine."""

    def escalader(message: str) -> None:
        notify("🆘 URGENCE PISCINE — " + message)
        if webhook:
            charge = json.dumps({"alerte": "piscine", "message": message}).encode("utf-8")
            try:
                if poster is not None:
                    poster(webhook, charge)
                else:
                    import urllib.request
                    req = urllib.request.Request(webhook, data=charge,
                                                 headers={"Content-Type": "application/json"})
                    urllib.request.urlopen(req, timeout=5).close()
            except Exception:
                log.exception("webhook d'escalade piscine")

    return escalader


class PoolWatcher:
    """Écoute les évènements Frigate sur MQTT et déclenche la réaction piscine."""

    def __init__(self, guard: PoolGuard, zones: tuple, camera: str = "",
                 host: str = "localhost", port: int = 1883, topic: str = "frigate/events",
                 username: str = "", password: str = "", client=None):
        self.guard, self.zones, self.camera = guard, zones, camera
        self.host, self.port, self.topic = host, port, topic
        self.username, self.password = username, password
        self._client = client

    def traiter(self, charge: bytes) -> None:
        info = analyser_frigate(charge, self.zones, self.camera)
        if info is not None:
            try:
                self.guard.sur_detection(info)
            except Exception:
                log.exception("réaction piscine")

    def demarrer(self) -> dict:
        if self._client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                return {"statut": "erreur", "message": "paho-mqtt manquant (pip install paho-mqtt)"}
            self._client = mqtt.Client()
        if self.username:
            self._client.username_pw_set(self.username, self.password)
        self._client.on_message = lambda c, u, msg: self.traiter(msg.payload)
        try:
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.subscribe(self.topic)
        except OSError as exc:
            return {"statut": "erreur", "message": f"MQTT injoignable : {exc}"}
        threading.Thread(target=self._client.loop_forever, name="jarvis-piscine", daemon=True).start()
        log.info("🏊 Surveillance piscine à l'écoute (%s)", self.topic)
        return {"statut": "succès", "message": "Surveillance piscine active"}


# Garde partagée entre les outils (armer/annuler) et la veille MQTT.
_GUARD: "PoolGuard | None" = None


def guard(home, notify) -> "PoolGuard | None":
    global _GUARD
    import config
    from skills import JsonStore

    if not (config.POOL and config.POOL_ZONES):
        return None
    if _GUARD is None:
        _GUARD = PoolGuard(home, notify, JsonStore(config.POOL_FILE, {}),
                           settings=config.piscine_settings(),
                           escalader=make_escalader(notify, config.POOL_WEBHOOK))
    return _GUARD


def build_pool_tools(home, notify) -> list:
    g = guard(home, notify)
    return _tools_from_guard(g) if g is not None else []


def make_poolguard(home, notify, evidence=None) -> "PoolWatcher | None":
    import config

    g = guard(home, notify)
    if g is None:
        return None
    g.notify = notify                       # le bot a un meilleur canal d'alerte que on_status
    g.evidence = evidence
    g.escalader = make_escalader(notify, config.POOL_WEBHOOK)
    return PoolWatcher(g, config.POOL_ZONES, config.POOL_CAMERA,
                       host=config.MQTT_HOST, port=config.MQTT_PORT,
                       username=config.MQTT_USER, password=config.MQTT_PASS)
