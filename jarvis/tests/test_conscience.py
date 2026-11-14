"""Tests de la conscience de situation (relie les capteurs, réfléchit, n'agit pas)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from conscience import Conscience, build_conscience_tools  # noqa: E402


class FauxRenfort:
    def __init__(self, available=True, reponse="Tout semble calme, Monsieur."):
        self.available = available
        self.reponse = reponse
        self.recu = None

    def ask(self, question, contexte=""):
        self.recu = (question, contexte)
        return self.reponse


def test_percevoir_collecte_les_sources():
    c = Conscience({"heure": lambda: "20h", "maison": lambda: "salon 21°C"}, lambda q, x: "")
    snap = c.percevoir()
    assert snap == {"heure": "20h", "maison": "salon 21°C"}


def test_percevoir_tolere_une_source_en_panne():
    def boom():
        raise RuntimeError("capteur HS")
    c = Conscience({"ok": lambda: "va bien", "ko": boom}, lambda q, x: "")
    assert c.percevoir() == {"ok": "va bien"}      # la panne est ignorée, pas de crash


def test_percevoir_ignore_les_vides():
    c = Conscience({"a": lambda: "", "b": lambda: "x"}, lambda q, x: "")
    assert c.percevoir() == {"b": "x"}


def test_reflechir_passe_les_perceptions_au_renfort():
    renfort = FauxRenfort(reponse="La cuisine est chaude alors que la maison semble vide.")
    c = Conscience({"maison": lambda: "cuisine 80°C", "présence": lambda: "aucune"}, renfort.ask)
    out = c.reflechir()
    assert "cuisine" in out
    # le contexte envoyé au renfort contient bien les deux perceptions
    assert "cuisine 80°C" in renfort.recu[1] and "aucune" in renfort.recu[1]


def test_reflechir_sans_perception():
    c = Conscience({}, lambda q, x: "ne devrait pas être appelé")
    assert "aucune perception" in c.reflechir()


def test_reflechir_renfort_en_panne():
    def boom(q, x=""):
        raise RuntimeError("renfort absent")
    c = Conscience({"a": lambda: "x"}, boom)
    assert "n'arrive pas" in c.reflechir()


# --- Outil ---

def test_pas_d_outil_sans_renfort():
    assert build_conscience_tools(None, FauxRenfort(available=False)) == []


def test_outil_present_avec_renfort():
    tools = build_conscience_tools(None, FauxRenfort())
    assert len(tools) == 1 and tools[0].name == "fais_le_point"
    assert "calme" in tools[0].run()
