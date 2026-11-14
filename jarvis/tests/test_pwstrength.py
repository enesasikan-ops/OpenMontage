"""Tests de l'évaluation de robustesse (local, aucune attaque)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pwstrength import build_pwcheck_tools, evaluer, message  # noqa: E402


def test_mot_de_passe_courant_critique():
    assert evaluer("azerty")["niveau"] == "critique"
    assert evaluer("password")["niveau"] == "critique"
    assert evaluer("123456")["niveau"] == "critique"


def test_que_des_chiffres():
    assert evaluer("849302")["niveau"] == "critique"      # uniquement des chiffres


def test_repetition_et_suite():
    assert evaluer("aaaaaaaa")["niveau"] == "critique"
    assert evaluer("abcd1234")["niveau"] == "critique"    # suite évidente


def test_court_est_faible():
    assert evaluer("aB3!")["niveau"] in ("critique", "faible")


def test_moyen():
    r = evaluer("Chat2019tarte")
    assert r["niveau"] in ("moyen", "correct") and r["bits"] > 40


def test_phrase_de_passe_forte():
    r = evaluer("Cheval-Agrafe-Correct-Batterie-72")
    assert r["niveau"] in ("correct", "fort") and r["bits"] >= 60


def test_vide():
    assert evaluer("")["niveau"] == "critique"


def test_message_contient_conseil():
    msg = message("azerty")
    assert "critique" in msg and "Wi-Fi" in msg


def test_rien_n_est_stocke_ni_renvoye():
    # l'évaluation ne renvoie qu'un verdict, jamais le mot de passe
    r = evaluer("MonMotDePasseSecret123")
    assert "MonMotDePasseSecret123" not in str(r)


# --- Outil ---

def test_outil():
    tools = build_pwcheck_tools()
    assert len(tools) == 1 and tools[0].name == "verifier_mot_de_passe"
    out = tools[0].run(mot_de_passe="azerty")
    assert "critique" in out
