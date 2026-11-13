"""Créer des automatisations Home Assistant en langage naturel.

« Quand je dis bonne nuit, éteins tout et verrouille la porte. »
→ Jarvis traduit (via le renfort) en règle Home Assistant, te la montre, et ne la
crée qu'après ta confirmation. Réversible : une automatisation se supprime dans HA.
"""

from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger(__name__)

DOMAINES = ("light", "switch", "lock", "cover", "scene", "climate", "fan",
            "input_boolean", "media_player")
MAX_ENTITES = 60


def _extraire_json(texte: str) -> "dict | None":
    bloc = re.search(r"```(?:json)?\s*\n(.*?)```", texte or "", re.DOTALL)
    brut = bloc.group(1) if bloc else (texte or "")
    debut = brut.find("{")
    if debut == -1:
        return None
    try:
        return json.loads(brut[debut:brut.rfind("}") + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _slug(texte: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (texte or "").lower()).strip("_")
    return (s or "auto")[:40]


class AutomationBuilder:
    def __init__(self, home, ask):
        self.home = home        # SmartHome : states() + _request()
        self.ask = ask          # renfort.ask(prompt) -> texte
        self._cache: dict[str, dict] = {}

    def _entites(self) -> str:
        lignes = []
        for e in self.home.states():
            dom = e["entity_id"].split(".")[0]
            if dom in DOMAINES:
                nom = e.get("attributes", {}).get("friendly_name", "")
                lignes.append(f"{e['entity_id']} ({nom})" if nom else e["entity_id"])
            if len(lignes) >= MAX_ENTITES:
                break
        return "\n".join(lignes) or "(aucune)"

    def proposer(self, description: str) -> "tuple[dict | None, str]":
        prompt = (
            "Traduis cette demande en automatisation Home Assistant, au format JSON.\n"
            f"Demande : {description}\n\n"
            "Appareils disponibles (utilise UNIQUEMENT ces entity_id) :\n"
            f"{self._entites()}\n\n"
            "Réponds UNIQUEMENT par un objet JSON avec les clés : \"alias\" (titre court), "
            "\"trigger\" (liste de déclencheurs HA), \"condition\" (liste, souvent vide), "
            "\"action\" (liste d'actions HA, ex. service light.turn_off avec target.entity_id). "
            "Pas de texte autour du JSON."
        )
        config = _extraire_json(self.ask(prompt))
        if not config or "action" not in config or "trigger" not in config:
            return None, "Je n'ai pas réussi à construire une automatisation valide."
        config.setdefault("alias", description[:50])
        config.setdefault("condition", [])
        config.setdefault("mode", "single")
        self._cache[description] = config
        return config, self.resume(config)

    @staticmethod
    def resume(config: dict) -> str:
        n_t = len(config.get("trigger", []))
        actions = config.get("action", [])
        services = [a.get("service", "?") for a in actions if isinstance(a, dict)]
        return (f"« {config.get('alias', 'sans titre')} » : {n_t} déclencheur(s), "
                f"{len(actions)} action(s) ({', '.join(services) or '—'})")

    def creer(self, description: str) -> str:
        config = self._cache.get(description)
        if config is None:
            config, _ = self.proposer(description)
            if config is None:
                return "Je n'ai pas pu créer l'automatisation."
        aid = f"jarvis_{_slug(config.get('alias', ''))}_{int(time.time())}"
        try:
            self.home._request("POST", f"/api/config/automation/config/{aid}", config)
            self.home._request("POST", "/api/services/automation/reload")
        except Exception as exc:
            log.error("création d'automatisation : %s", exc)
            return "Je n'ai pas pu enregistrer l'automatisation dans Home Assistant."
        self._cache.pop(description, None)
        return f"C'est fait : automatisation « {config.get('alias')} » créée et active."


def build_automation_tools(home, ask) -> list:
    from tools import Tool

    builder = AutomationBuilder(home, ask)

    def confirmer(description: str) -> str:
        _, resume = builder.proposer(description)
        return f"Je vais créer cette automatisation — {resume}"

    return [Tool(
        name="creer_automatisation",
        description=("Crée une automatisation dans la maison connectée à partir d'une demande "
                     "en langage naturel (« quand je dis bonne nuit, éteins tout »). "
                     "À utiliser pour une RÈGLE durable, pas pour une action immédiate."),
        parameters={"type": "object",
                    "properties": {"description": {"type": "string",
                                   "description": "la règle voulue, en français"}},
                    "required": ["description"]},
        run=builder.creer,
        confirm=confirmer,
    )]
