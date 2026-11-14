"""Tests du planificateur multi-angles (propose, n'exécute pas, jamais « infaillible »)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from council import build_planner_tools  # noqa: E402


class FauxRenfort:
    def __init__(self, available=True, reponse="PLAN: ferme les volets côté vent."):
        self.available = available
        self.reponse = reponse
        self.demande = None

    def ask(self, question, contexte=""):
        self.demande = (question, contexte)
        return self.reponse


def test_pas_d_outil_sans_renfort():
    assert build_planner_tools(FauxRenfort(available=False)) == []
    assert build_planner_tools(object()) == []           # objet sans .ask


def test_outil_present_avec_renfort():
    tools = build_planner_tools(FauxRenfort())
    assert len(tools) == 1 and tools[0].name == "preparer_la_maison"


def test_prompt_multi_angles_et_anti_infaillible():
    renfort = FauxRenfort()
    tool = build_planner_tools(renfort)[0]
    tool.run(objectif="une tempête hivernale de 3 jours")
    question = renfort.demande[0]
    assert "tempête hivernale de 3 jours" in question
    assert "volets motorisés" in question                # il force à chercher les conflits
    assert "infaillible" in question                     # … et interdit de le prétendre
    assert "HYPOTHÈSES" in question and "RISQUES" in question


def test_reponse_encadree_proposition():
    tool = build_planner_tools(FauxRenfort(reponse="1. ..."))[0]
    out = tool.run(objectif="canicule")
    assert "à valider" in out and "sans votre accord" in out   # proposition, pas exécution


def test_objectif_vide():
    tool = build_planner_tools(FauxRenfort())[0]
    assert "préparer" in tool.run(objectif="  ")


def test_passe_le_contexte():
    renfort = FauxRenfort()
    build_planner_tools(renfort)[0].run(objectif="absence 1 semaine", contexte="chat à nourrir")
    assert renfort.demande[1] == "chat à nourrir"
