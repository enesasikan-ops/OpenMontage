"""Pilotage de la maison connectée via Home Assistant (local).

Home Assistant tourne sur le réseau local (souvent sur le même mini-PC). Il a
déjà fait le travail d'intégration de milliers d'objets (lumières, prises,
volets, serrures, capteurs...). Jarvis lui parle par son accès officiel, avec
un jeton que tu génères une fois.

Tout reste sur le réseau local : ça marche même en mode 100 % hors ligne.
Les actions sensibles (serrures, portail, volets, alarme) demandent confirmation.
"""

import json
import unicodedata
import urllib.error
import urllib.request
from typing import Callable

import config

# Domaines Home Assistant par type d'action.
ON_OFF_DOMAINS = ("light", "switch", "fan", "media_player", "input_boolean")
LIGHT_DOMAINS = ("light",)
COVER_DOMAINS = ("cover",)      # volets, portail, porte de garage
LOCK_DOMAINS = ("lock",)        # serrures
READABLE = ("sensor", "binary_sensor", "climate", "weather")

STOPWORDS = {"la", "le", "les", "l", "du", "de", "des", "d", "un", "une",
            "mon", "ma", "mes", "the", "au", "aux"}
ALL_WORDS = {"tout", "toute", "toutes", "tous"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(w for w in "".join(c if c.isalnum() else " " for c in text).split()
                    if w not in STOPWORDS)


def _match(query: str, friendly: str) -> int:
    """Score de correspondance entre ce que dit l'utilisateur et le nom d'un appareil."""
    q, f = set(_norm(query).split()), set(_norm(friendly).split())
    if not q or not f:
        return 0
    common = q & f
    if not common:
        return 0
    return len(common) * 10 + (5 if q <= f else 0)  # bonus si tous les mots demandés collent


class SmartHome:
    def __init__(self, base_url: str = "", token: str = "",
                 request: Callable | None = None):
        self.base = (base_url or config.HA_URL).rstrip("/")
        self.token = token or config.HA_TOKEN
        self._request = request or self._http

    @property
    def configured(self) -> bool:
        return bool(self.base and self.token)

    def _http(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:  # noqa: S310 (URL locale configurée)
            text = response.read().decode("utf-8")
        return json.loads(text) if text else None

    # --- Accès bas niveau ---------------------------------------------------------

    def states(self) -> list[dict]:
        return self._request("GET", "/api/states") or []

    def call(self, domain: str, service: str, entity_id, **data):
        self._request("POST", f"/api/services/{domain}/{service}",
                      {"entity_id": entity_id, **data})

    @staticmethod
    def _name(entity: dict) -> str:
        return entity.get("attributes", {}).get("friendly_name") or entity["entity_id"]

    def resolve(self, query: str, domains: tuple[str, ...]) -> list[dict]:
        """Trouve les appareils d'un domaine qui correspondent à ce que dit l'utilisateur.

        « tout » / « toutes » → tous les appareils du domaine.
        """
        entities = [e for e in self.states() if e["entity_id"].split(".")[0] in domains]
        if _norm(query) in ALL_WORDS or not query.strip():
            return entities
        scored = [(_match(query, self._name(e)), e) for e in entities]
        best = max((s for s, _ in scored), default=0)
        if best == 0:
            return []
        return [e for s, e in scored if s == best]

    # --- Actions ----------------------------------------------------------------------

    def _guard(self):
        if not self.configured:
            return ("La maison connectée n'est pas configurée : renseigne HOMEASSISTANT_URL "
                    "et HOMEASSISTANT_TOKEN dans le fichier .env.")
        return None

    def _act(self, query, domains, service, label, past, **data) -> str:
        err = self._guard()
        if err:
            return err
        try:
            targets = self.resolve(query, domains)
        except urllib.error.HTTPError as exc:
            return ("Mon jeton Home Assistant est refusé, vérifie HOMEASSISTANT_TOKEN."
                    if exc.code in (401, 403) else "Home Assistant a renvoyé une erreur.")
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return "Je n'arrive pas à joindre la maison connectée. Home Assistant est-il allumé ?"
        if not targets:
            return f"Je ne trouve pas « {query} » dans la maison connectée."
        ids = [e["entity_id"] for e in targets]
        names = ", ".join(self._name(e) for e in targets)
        try:
            by_domain: dict[str, list[str]] = {}
            for eid in ids:
                by_domain.setdefault(eid.split(".")[0], []).append(eid)
            for domain, eids in by_domain.items():
                self.call(domain, service, eids, **data)
        except (urllib.error.URLError, OSError):
            return f"Je n'ai pas pu {label} {names}."
        return f"{past} : {names}."

    def turn_on(self, appareil: str) -> str:
        return self._act(appareil, ON_OFF_DOMAINS, "turn_on", "allumer", "C'est allumé")

    def turn_off(self, appareil: str) -> str:
        return self._act(appareil, ON_OFF_DOMAINS, "turn_off", "éteindre", "C'est éteint")

    def set_brightness(self, appareil: str, niveau) -> str:
        try:
            pct = max(0, min(100, int(float(niveau))))
        except (TypeError, ValueError):
            return "Donne un niveau entre 0 et 100."
        if pct == 0:
            return self.turn_off(appareil)
        return self._act(appareil, LIGHT_DOMAINS, "turn_on", "régler",
                         f"Réglé à {pct} %", brightness_pct=pct)

    def open_cover(self, appareil: str) -> str:
        return self._act(appareil, COVER_DOMAINS, "open_cover", "ouvrir", "Ouvert")

    def close_cover(self, appareil: str) -> str:
        return self._act(appareil, COVER_DOMAINS, "close_cover", "fermer", "Fermé")

    def lock(self, appareil: str) -> str:
        return self._act(appareil, LOCK_DOMAINS, "lock", "verrouiller", "Verrouillé")

    def unlock(self, appareil: str) -> str:
        return self._act(appareil, LOCK_DOMAINS, "unlock", "déverrouiller", "Déverrouillé")

    def run_scene(self, nom: str) -> str:
        err = self._guard()
        if err:
            return err
        try:
            targets = self.resolve(nom, ("scene", "script"))
        except (urllib.error.URLError, OSError, urllib.error.HTTPError, json.JSONDecodeError):
            return "Je n'arrive pas à joindre la maison connectée."
        if not targets:
            return f"Je ne trouve pas d'ambiance « {nom} »."
        entity = targets[0]
        domain = entity["entity_id"].split(".")[0]
        try:
            self.call(domain, "turn_on" if domain == "scene" else "turn_on", entity["entity_id"])
        except (urllib.error.URLError, OSError):
            return "Je n'ai pas pu lancer cette ambiance."
        return f"Ambiance lancée : {self._name(entity)}."

    # --- Lecture -----------------------------------------------------------------------

    def status(self, appareil: str = "") -> str:
        err = self._guard()
        if err:
            return err
        try:
            states = self.states()
        except (urllib.error.URLError, OSError, urllib.error.HTTPError, json.JSONDecodeError):
            return "Je n'arrive pas à joindre la maison connectée."
        if appareil.strip():
            matches = sorted(((_match(appareil, self._name(e)), e) for e in states),
                             key=lambda x: x[0], reverse=True)
            found = [e for s, e in matches if s > 0][:4]
            if not found:
                return f"Je ne trouve pas « {appareil} »."
            return ". ".join(f"{self._name(e)} : {self._readable(e)}" for e in found) + "."
        on = [self._name(e) for e in states
              if e["entity_id"].split(".")[0] in ("light", "switch") and e.get("state") == "on"]
        temps = [f"{self._name(e)} {e.get('state')} degrés" for e in states
                 if e["entity_id"].startswith("sensor.")
                 and e.get("attributes", {}).get("unit_of_measurement") in ("°C", "C")][:3]
        parts = [f"{len(on)} lumière(s) ou prise(s) allumée(s)" + (" : " + ", ".join(on) if on else "")]
        if temps:
            parts.append("Températures : " + ", ".join(temps))
        return ". ".join(parts) + "."

    @staticmethod
    def _readable(entity: dict) -> str:
        state = entity.get("state", "inconnu")
        unit = entity.get("attributes", {}).get("unit_of_measurement", "")
        fr = {"on": "allumé", "off": "éteint", "open": "ouvert", "closed": "fermé",
              "locked": "verrouillé", "unlocked": "déverrouillé", "home": "présent",
              "unavailable": "indisponible"}.get(state, state)
        return f"{fr} {unit}".strip()


def build_smarthome(home: SmartHome) -> list:
    from tools import Tool

    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    def resolved_names(query, domains) -> str:
        try:
            targets = home.resolve(query, domains)
        except Exception:
            return query
        return ", ".join(home._name(e) for e in targets) or f"« {query} »"

    return [
        Tool(name="allumer",
             description="Allume une lumière, une prise ou un appareil (« allume le salon », « allume tout »).",
             parameters=obj({"appareil": {**s, "description": "Nom de l'appareil ou de la pièce, ou « tout »."}},
                            ["appareil"]),
             run=home.turn_on),
        Tool(name="eteindre",
             description="Éteint une lumière, une prise ou un appareil (« éteins la chambre », « éteins tout »).",
             parameters=obj({"appareil": {**s, "description": "Nom de l'appareil ou de la pièce, ou « tout »."}},
                            ["appareil"]),
             run=home.turn_off),
        Tool(name="regler_lumiere",
             description="Règle l'intensité d'une lumière, de 0 à 100 % (« mets le salon à 30 % »).",
             parameters=obj({"appareil": s, "niveau": {"type": "integer", "description": "0 à 100."}},
                            ["appareil", "niveau"]),
             run=home.set_brightness),
        Tool(name="etat_maison",
             description=("Donne l'état de la maison connectée : ce qui est allumé, les températures, ou "
                          "l'état d'un appareil précis (« la porte est fermée ? », « température du salon »)."),
             parameters=obj({"appareil": {**s, "description": "Appareil précis, ou vide pour un résumé."}}, []),
             run=home.status),
        Tool(name="lancer_ambiance",
             description="Lance une ambiance ou un scénario Home Assistant (« ambiance cinéma », « bonne nuit »).",
             parameters=obj({"nom": {**s, "description": "Nom de l'ambiance ou du scénario."}}, ["nom"]),
             run=home.run_scene),
        Tool(name="ouvrir",
             description="Ouvre un volet, un portail ou la porte de garage.",
             parameters=obj({"appareil": s}, ["appareil"]),
             run=home.open_cover,
             confirm=lambda appareil: f"Je vais ouvrir : {resolved_names(appareil, COVER_DOMAINS)}."),
        Tool(name="fermer",
             description="Ferme un volet, un portail ou la porte de garage.",
             parameters=obj({"appareil": s}, ["appareil"]),
             run=home.close_cover,
             confirm=lambda appareil: f"Je vais fermer : {resolved_names(appareil, COVER_DOMAINS)}."),
        Tool(name="verrouiller",
             description="Verrouille une serrure connectée.",
             parameters=obj({"appareil": s}, ["appareil"]),
             run=home.lock,
             confirm=lambda appareil: f"Je vais verrouiller : {resolved_names(appareil, LOCK_DOMAINS)}."),
        Tool(name="deverrouiller",
             description="Déverrouille une serrure connectée.",
             parameters=obj({"appareil": s}, ["appareil"]),
             run=home.unlock,
             confirm=lambda appareil: f"Je vais déverrouiller : {resolved_names(appareil, LOCK_DOMAINS)}."),
    ]
