"""Tests du repli automatique : si Claude ne peut pas coder, Gemini prend le relais."""

import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import claude_bridge as cb  # noqa: E402
from claude_bridge import (  # noqa: E402
    ApiBackend, GeminiBackend, GeminiCliBackend, MentorEnCascade,
    SubscriptionBackend, _choisir_repli, _renfort_a_echoue,
)

QUOTA = "Tu as atteint la limite de ton abonnement Claude pour le moment. Je réponds avec mes moyens."


class FakeBackend:
    def __init__(self, available=True, ask="", delegate="", name="faux"):
        self.available = available
        self._ask, self._delegate, self.name = ask, delegate, name
        self.vu = []

    def unavailable_reason(self):
        return "indisponible"

    def ask(self, question, context=""):
        self.vu.append(("ask", question))
        return self._ask

    def delegate(self, task):
        self.vu.append(("delegate", task))
        return self._delegate


# --- Détection d'échec ---

def test_echec_reconnait_quota_et_pannes():
    assert _renfort_a_echoue(QUOTA)
    assert _renfort_a_echoue("Claude a renvoyé une erreur (503). Réessaie plus tard.")
    assert not _renfort_a_echoue("Voici ta réponse, tout va bien.")


def test_refus_de_securite_ne_declenche_pas_le_repli():
    # Un refus de sécurité ne doit JAMAIS être contourné en passant à Gemini.
    assert not _renfort_a_echoue("Claude a préféré ne pas répondre à cette question.")


# --- ask : bascule sur le repli en cas d'échec ---

def test_ask_bascule_sur_repli_si_claude_echoue():
    claude = FakeBackend(ask=QUOTA)
    gemini = FakeBackend(ask="Réponse de Gemini.")
    assert MentorEnCascade(claude, gemini).ask("Question ?") == "Réponse de Gemini."


def test_ask_garde_claude_si_ca_marche():
    claude = FakeBackend(ask="Réponse de Claude.")
    gemini = FakeBackend(ask="Gemini")
    assert MentorEnCascade(claude, gemini).ask("Question ?") == "Réponse de Claude."
    assert gemini.vu == []  # Gemini n'est même pas appelé


# --- delegate (coder) : Gemini propose, le pont écrit les fichiers dans l'atelier ---

def test_coder_ecrit_les_fichiers_de_gemini(tmp_path):
    folder = tmp_path / "prop"
    folder.mkdir()
    code = (
        "### fichier: meteo.py\n```python\ndef build_tools():\n    return []\n```\n"
        "### fichier: test_meteo.py\n```python\ndef test_ok():\n    assert True\n```\n"
    )
    claude = FakeBackend(delegate=QUOTA)        # Claude n'a plus de quota
    gemini = FakeBackend(ask=code)              # Gemini propose le code
    task = f"Dossier de travail à utiliser (et uniquement lui) : {folder}\nAjoute la météo."
    out = MentorEnCascade(claude, gemini).delegate(task)

    assert "Gemini a pris le relais" in out
    assert (folder / "meteo.py").read_text().startswith("def build_tools")
    assert (folder / "test_meteo.py").exists()   # le test existe -> run_tests pourra tourner


def test_coder_refuse_la_traversee_de_chemin(tmp_path):
    folder = tmp_path / "prop"
    folder.mkdir()
    code = "### fichier: ../evasion.py\n```python\nx = 1\n```\n"
    out = MentorEnCascade(FakeBackend(delegate=QUOTA), FakeBackend(ask=code)).delegate(
        f"Dossier de travail à utiliser : {folder}\nfais un truc")
    assert not (tmp_path / "evasion.py").exists()   # rien écrit hors du dossier
    assert "Fichiers proposés :" in out             # (liste vide, mais pas de fuite)


def test_claude_garde_la_main_si_il_code(tmp_path):
    claude = FakeBackend(delegate="J'ai créé le script dans l'atelier.")
    gemini = FakeBackend(ask="ne doit pas servir")
    out = MentorEnCascade(claude, gemini).delegate("Dossier de travail à utiliser : /x\nfais")
    assert out == "J'ai créé le script dans l'atelier."
    assert gemini.vu == []


# --- Choix du repli ---

def test_repli_seulement_si_principal_est_claude(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "RENFORT_REPLI", "gemini")
    monkeypatch.setattr(config, "GEMINI_KEY", "cle")
    # Principal Claude -> repli Gemini
    assert isinstance(_choisir_repli(SubscriptionBackend()), GeminiBackend)
    # Principal déjà Gemini -> pas de repli (il est déjà là)
    assert _choisir_repli(GeminiBackend()) is None
    assert _choisir_repli(GeminiCliBackend()) is None


def test_repli_desactive(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "RENFORT_REPLI", "aucun")
    assert _choisir_repli(SubscriptionBackend()) is None


def test_offline_pas_de_repli(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", True)
    monkeypatch.setattr(config, "RENFORT_REPLI", "gemini")
    assert _choisir_repli(ApiBackend()) is None
