"""Tests des consignes de comportement (améliorer sa pensée, dicté par toi)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import persona  # noqa: E402
from preferences import Preferences, build_preference_tools, directives  # noqa: E402


def test_ajouter_et_persister(tmp_path):
    p = Preferences(tmp_path / "c.json")
    p.ajouter("sois plus bref sur la sécurité")
    assert Preferences(tmp_path / "c.json").items == ["sois plus bref sur la sécurité"]


def test_pas_de_doublon(tmp_path):
    p = Preferences(tmp_path / "c.json")
    p.ajouter("propose avant d'agir")
    assert "déjà" in p.ajouter("propose avant d'agir")


def test_retirer(tmp_path):
    p = Preferences(tmp_path / "c.json")
    p.ajouter("rappelle-moi les piles faibles")
    assert "abandonne" in p.retirer("piles") and p.items == []
    assert "Aucune" in p.retirer("inexistant")


def test_directives_vide(tmp_path):
    assert directives(Preferences(tmp_path / "c.json")) == ""


def test_directives_bloc(tmp_path):
    p = Preferences(tmp_path / "c.json")
    p.ajouter("sois bref")
    d = directives(p)
    assert "Consignes personnelles" in d and "- sois bref" in d


def test_injecte_dans_le_prompt(monkeypatch, tmp_path):
    chemin = tmp_path / "c.json"
    Preferences(chemin).ajouter("rappelle toujours les intrusions réseau")
    monkeypatch.setattr(config, "PREFERENCES_FILE", chemin)
    monkeypatch.setattr(config, "STYLE", "film")
    assert "intrusions réseau" in persona.character()


# --- Outils ---

def test_outils(monkeypatch, tmp_path):
    prefs = Preferences(tmp_path / "c.json")
    tools = {t.name: t for t in build_preference_tools(prefs)}
    assert set(tools) == {"retenir_consigne", "oublier_consigne", "mes_consignes"}
    assert "pas de consigne" in tools["mes_consignes"].run()
    tools["retenir_consigne"].run(consigne="sois plus direct")
    assert "sois plus direct" in tools["mes_consignes"].run()
    tools["oublier_consigne"].run(mot="direct")
    assert "pas de consigne" in tools["mes_consignes"].run()
