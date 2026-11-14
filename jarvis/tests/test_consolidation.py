"""Tests de la consolidation de mémoire (« sommeil cognitif » : propose, n'écrase pas)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from consolidation import (ConsolidationManager,  # noqa: E402
                           build_consolidation_tools)


class FakeMemory:
    def __init__(self, faits):
        self.facts = list(faits)
        self.sauve = 0

    def _save(self):
        self.sauve += 1


def _renfort(reponse):
    appels = {"n": 0}

    def demander(question, contexte=""):
        appels["n"] += 1
        return reponse

    demander.appels = appels
    return demander


FAITS = ["aime le café le matin", "aime le café le matin le matin",
         "température de 21°C relevée mardi", "prépare un voyage à Lyon"]


def test_proposer_resume_le_changement():
    mem = FakeMemory(FAITS)
    rep = json.dumps({"faits": ["aime le café le matin", "prépare un voyage à Lyon"],
                      "changements": "doublons fusionnés, relevé ponctuel oublié"})
    mgr = ConsolidationManager(mem, _renfort(rep))
    out = mgr.proposer()
    assert "4 faits → 2" in out and "doublons fusionnés" in out
    assert mem.facts == FAITS and mem.sauve == 0        # proposer ne touche à rien


def test_appliquer_apres_proposer():
    mem = FakeMemory(FAITS)
    rep = json.dumps({"faits": ["aime le café le matin", "prépare un voyage à Lyon"]})
    mgr = ConsolidationManager(mem, _renfort(rep))
    mgr.proposer()
    out = mgr.appliquer()
    assert mem.facts == ["aime le café le matin", "prépare un voyage à Lyon"]
    assert mem.sauve == 1 and "2 faits conservés" in out


def test_memoire_vide():
    mgr = ConsolidationManager(FakeMemory([]), _renfort("{}"))
    assert "vide" in mgr.proposer()


def test_reponse_illisible_ne_touche_a_rien():
    mem = FakeMemory(FAITS)
    mgr = ConsolidationManager(mem, _renfort("désolé, je ne sais pas"))
    out = mgr.proposer()
    assert "échoué" in out and mem.facts == FAITS


def test_refuse_de_tout_vider():
    mem = FakeMemory(FAITS)
    mgr = ConsolidationManager(mem, _renfort(json.dumps({"faits": []})))
    out = mgr.proposer()
    assert "refuse" in out and mem.facts == FAITS


def test_appliquer_sans_proposition_prepare_d_abord():
    mem = FakeMemory(FAITS)
    rep = json.dumps({"faits": ["aime le café le matin"]})
    mgr = ConsolidationManager(mem, _renfort(rep))
    out = mgr.appliquer()                               # pas de proposer() avant
    assert "Consolidation proposée" in out and mem.sauve == 0   # il propose, n'applique pas


def test_renfort_en_panne():
    def boom(q, c=""):
        raise RuntimeError("renfort absent")
    out = ConsolidationManager(FakeMemory(FAITS), boom).proposer()
    assert "n'ai pas pu" in out


# --- Outil ---

class FauxRenfort:
    def __init__(self, available=True, reponse="{}"):
        self.available = available
        self.reponse = reponse

    def ask(self, question, contexte=""):
        return self.reponse


def test_pas_d_outil_sans_renfort():
    assert build_consolidation_tools(FakeMemory(FAITS), FauxRenfort(available=False)) == []


def test_outil_propose_puis_applique():
    mem = FakeMemory(FAITS)
    rep = json.dumps({"faits": ["aime le café", "voyage à Lyon"], "changements": "nettoyé"})
    tool = build_consolidation_tools(mem, FauxRenfort(reponse=rep))[0]
    assert tool.name == "consolider_memoire"
    desc = tool.confirm()                               # décrit l'effet (garde-fou)
    assert "→ 2" in desc and mem.facts == FAITS
    tool.run()                                          # applique après accord
    assert mem.facts == ["aime le café", "voyage à Lyon"]
