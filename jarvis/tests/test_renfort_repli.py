"""Tests du repli automatique du renfort, dans les deux sens (Claude ↔ Gemini)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from claude_bridge import (  # noqa: E402
    ApiBackend, GeminiBackend, GeminiCliBackend, MentorEnCascade,
    SubscriptionBackend, _choisir_repli, _ne_sait_pas_agir, _renfort_a_echoue,
)

QUOTA = "Tu as atteint la limite de ton abonnement Claude pour le moment. Je réponds avec mes moyens."
QUOTA_GEMINI = "Ta limite Gemini est atteinte pour le moment."
# Ce que renvoie un renfort qui sait répondre mais pas piloter la machine (Gemini, Claude API).
NE_AGIT_PAS = "Pour exécuter une vraie tâche sur l'ordinateur, il me faut Claude Code (mode abonnement)."
CODE = (
    "### fichier: meteo.py\n```python\ndef build_tools():\n    return []\n```\n"
    "### fichier: test_meteo.py\n```python\ndef test_ok():\n    assert True\n```\n"
)


class Faux:
    """Faux renfort : delegate et ask renvoient ce qu'on lui dit."""

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


def _gemini(ask=CODE):
    """Un renfort façon Gemini : il n'agit pas (delegate), mais il propose (ask)."""
    return Faux(ask=ask, delegate=NE_AGIT_PAS, name="Gemini")


def _claude_agit(resume="J'ai créé le script dans l'atelier."):
    """Un renfort façon Claude Code : il agit directement (delegate)."""
    return Faux(delegate=resume, name="Claude")


# --- Détection ---

def test_echec_reconnait_quota_des_deux():
    assert _renfort_a_echoue(QUOTA) and _renfort_a_echoue(QUOTA_GEMINI)
    assert _renfort_a_echoue("Gemini a renvoyé une erreur (503). Réessaie plus tard.")
    assert not _renfort_a_echoue("Voici ta réponse, tout va bien.")


def test_refus_de_securite_ne_declenche_pas_le_repli():
    assert not _renfort_a_echoue("Claude a préféré ne pas répondre à cette question.")
    assert not _renfort_a_echoue("Gemini a préféré ne pas répondre.")


def test_ne_sait_pas_agir_est_distinct_d_un_echec():
    assert _ne_sait_pas_agir(NE_AGIT_PAS)        # sait répondre, pas agir
    assert not _renfort_a_echoue(NE_AGIT_PAS)    # ce n'est PAS un échec réel


# --- ask : bascule sur le repli en cas d'échec réel ---

def test_ask_bascule_si_principal_echoue():
    assert MentorEnCascade(Faux(ask=QUOTA), Faux(ask="Réponse B")).ask("?") == "Réponse B"


def test_ask_garde_le_principal_si_ca_marche():
    repli = Faux(ask="B")
    assert MentorEnCascade(Faux(ask="Réponse A"), repli).ask("?") == "Réponse A"
    assert repli.vu == []


# --- Sens 1 : Gemini devant, propose le code, Jarvis écrit les fichiers ---

def test_gemini_principal_propose_et_ecrit(tmp_path):
    folder = tmp_path / "prop"
    folder.mkdir()
    repli_claude = _claude_agit()
    out = MentorEnCascade(_gemini(), repli_claude).delegate(
        f"Dossier de travail à utiliser (et uniquement lui) : {folder}\nAjoute la météo.")
    assert "Fichiers proposés" in out
    assert (folder / "meteo.py").read_text().startswith("def build_tools")
    assert (folder / "test_meteo.py").exists()
    assert repli_claude.vu == []   # Gemini a suffi, Claude pas sollicité


# --- Sens 2 : Claude devant, agit directement ---

def test_claude_principal_agit_directement(tmp_path):
    repli = _gemini()
    out = MentorEnCascade(_claude_agit(), repli).delegate(
        f"Dossier de travail à utiliser : {tmp_path}\nfais")
    assert out == "J'ai créé le script dans l'atelier."
    assert repli.vu == []


# --- Bascule : le principal est en panne (quota), le relais prend la main ---

def test_bascule_gemini_en_panne_vers_claude(tmp_path):
    # Gemini devant mais à court de quota -> Claude (qui agit) prend le relais
    gemini_hs = Faux(ask=QUOTA_GEMINI, delegate=NE_AGIT_PAS, name="Gemini")
    out = MentorEnCascade(gemini_hs, _claude_agit()).delegate(
        f"Dossier de travail à utiliser : {tmp_path}\nfais")
    assert "a pris le relais" in out and "J'ai créé le script" in out


def test_bascule_claude_en_panne_vers_gemini(tmp_path):
    folder = tmp_path / "prop"
    folder.mkdir()
    out = MentorEnCascade(Faux(delegate=QUOTA, name="Claude"), _gemini()).delegate(
        f"Dossier de travail à utiliser : {folder}\nfais")
    assert "a pris le relais" in out
    assert (folder / "meteo.py").exists()


# --- Sécurité : pas d'écriture hors du dossier de travail ---

def test_refuse_la_traversee_de_chemin(tmp_path):
    folder = tmp_path / "prop"
    folder.mkdir()
    code = "### fichier: ../evasion.py\n```python\nx = 1\n```\n"
    MentorEnCascade(_gemini(ask=code), Faux()).delegate(
        f"Dossier de travail à utiliser : {folder}\nfais")
    assert not (tmp_path / "evasion.py").exists()   # rien écrit hors du dossier


# --- Choix du repli ---

def test_auto_claude_principal_prend_gemini(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "RENFORT_REPLI", "auto")
    monkeypatch.setattr(config, "GEMINI_CLI_ENABLE", False)
    monkeypatch.setattr(config, "GEMINI_KEY", "cle")
    assert isinstance(_choisir_repli(SubscriptionBackend()), GeminiBackend)


def test_pas_de_repli_vers_soi_meme(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "RENFORT_REPLI", "gemini")
    monkeypatch.setattr(config, "GEMINI_KEY", "cle")
    # Principal déjà Gemini : on ne le double pas avec un autre Gemini
    assert _choisir_repli(GeminiBackend()) is None
    assert _choisir_repli(GeminiCliBackend()) is None


def test_repli_desactive_et_offline(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)
    monkeypatch.setattr(config, "RENFORT_REPLI", "aucun")
    assert _choisir_repli(SubscriptionBackend()) is None
    monkeypatch.setattr(config, "OFFLINE", True)
    monkeypatch.setattr(config, "RENFORT_REPLI", "gemini")
    assert _choisir_repli(ApiBackend()) is None
