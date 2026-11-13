"""Tests de la création d'automatisations Home Assistant."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automations import AutomationBuilder, _extraire_json, build_automation_tools  # noqa: E402

CONFIG = {
    "alias": "Bonne nuit",
    "trigger": [{"platform": "conversation", "command": "bonne nuit"}],
    "action": [{"service": "light.turn_off", "target": {"entity_id": "all"}},
               {"service": "lock.lock", "target": {"entity_id": "lock.porte"}}],
}


class FauxHome:
    def __init__(self, reponse_config=None):
        self.reponse = reponse_config if reponse_config is not None else CONFIG
        self.appels = []

    def states(self):
        return [{"entity_id": "light.salon", "attributes": {"friendly_name": "Salon"}},
                {"entity_id": "lock.porte", "attributes": {"friendly_name": "Porte"}},
                {"entity_id": "sensor.temp", "attributes": {"friendly_name": "Temp"}}]  # ignoré (domaine)

    def _request(self, method, path, body=None):
        self.appels.append((method, path, body))


def _ask(reponse):
    return lambda prompt: reponse


# --- Extraction JSON ---

def test_extraction_json_avec_balises():
    assert _extraire_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extraire_json('voici: {"a": 2} voilà') == {"a": 2}
    assert _extraire_json("pas de json") is None


# --- Proposition ---

def test_proposer_construit_et_cache():
    home = FauxHome()
    b = AutomationBuilder(home, _ask(json.dumps(CONFIG)))
    config, resume = b.proposer("quand je dis bonne nuit, éteins tout et verrouille")
    assert config["alias"] == "Bonne nuit"
    assert "2 action(s)" in resume and "light.turn_off" in resume
    assert "quand je dis bonne nuit, éteins tout et verrouille" in b._cache


def test_proposer_json_invalide():
    b = AutomationBuilder(FauxHome(), _ask("je ne sais pas faire"))
    config, resume = b.proposer("fais un truc")
    assert config is None and "valide" in resume


def test_entites_filtre_les_domaines():
    b = AutomationBuilder(FauxHome(), _ask("{}"))
    entites = b._entites()
    assert "light.salon" in entites and "lock.porte" in entites
    assert "sensor.temp" not in entites   # capteur : pas un appareil pilotable


# --- Création : POST vers HA + reload ---

def test_creer_envoie_a_home_assistant():
    home = FauxHome()
    b = AutomationBuilder(home, _ask(json.dumps(CONFIG)))
    b.proposer("bonne nuit")
    out = b.creer("bonne nuit")
    assert "créée" in out
    chemins = [p for _, p, _ in home.appels]
    assert any("/api/config/automation/config/jarvis_bonne_nuit_" in p for p in chemins)
    assert "/api/services/automation/reload" in chemins


# --- L'outil : confirmation obligatoire ---

def test_outil_a_une_confirmation():
    home = FauxHome()
    tools = build_automation_tools(home, _ask(json.dumps(CONFIG)))
    assert len(tools) == 1 and tools[0].name == "creer_automatisation"
    assert tools[0].confirm is not None
    message = tools[0].confirm("bonne nuit")
    assert "Je vais créer" in message and home.appels == []   # rien créé tant que pas confirmé
