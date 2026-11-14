"""Tests : anonymisation des données envoyées au renfort cloud (vie privée).

Invariant : avant qu'un texte parte vers Claude/Gemini, le prénom du propriétaire et
sa ville sont remplacés par des termes neutres. Un seul point de contrôle (_format),
donc tous les chemins ask() en bénéficient.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import claude_bridge  # noqa: E402
from claude_bridge import GeminiBackend, SYSTEM_PROMPT, _anonymiser, _format  # noqa: E402


def _anonyme(monkeypatch, actif=True, nom="Enes", ville="Lyon"):
    monkeypatch.setattr(config, "RENFORT_ANONYME", actif)
    monkeypatch.setattr(config, "USER_NAME", nom)
    monkeypatch.setattr(config, "CITY", ville)


def test_retire_prenom_et_ville(monkeypatch):
    _anonyme(monkeypatch)
    out = _anonymiser("Enes habite à Lyon et aime le café")
    assert "Enes" not in out and "Lyon" not in out
    assert "propriétaire" in out and "région" in out


def test_insensible_a_la_casse(monkeypatch):
    _anonyme(monkeypatch)
    assert "enes" not in _anonymiser("ENES et enes").lower()


def test_respecte_les_frontieres_de_mots(monkeypatch):
    _anonyme(monkeypatch, nom="Enes", ville="Lyon")
    # ne doit pas massacrer un mot qui CONTIENT le prénom/la ville
    out = _anonymiser("Enesto travaille à Lyonnais")
    assert "Enesto" in out and "Lyonnais" in out


def test_desactive_laisse_passer(monkeypatch):
    _anonyme(monkeypatch, actif=False)
    assert _anonymiser("Enes habite à Lyon") == "Enes habite à Lyon"


def test_nom_trop_court_ignore(monkeypatch):
    # un prénom d'une seule lettre n'est pas scrubé (éviter de tout remplacer)
    _anonyme(monkeypatch, nom="E", ville="")
    assert _anonymiser("E comme Edouard") == "E comme Edouard"


def test_format_anonymise_question_et_contexte(monkeypatch):
    _anonyme(monkeypatch)
    out = _format("Qui est Enes ?", "Enes vit à Lyon")
    assert "Enes" not in out and "Lyon" not in out
    assert "Contexte" in out and "Question" in out


def test_system_prompt_par_defaut_sans_prenom():
    # avec l'anonymisation par défaut (ON), le prompt système ne contient pas le vrai prénom
    assert config.USER_NAME not in SYSTEM_PROMPT
    assert "propriétaire" in SYSTEM_PROMPT


def test_ask_gemini_n_envoie_pas_le_prenom(monkeypatch):
    _anonyme(monkeypatch)
    vus = {}

    def faux_request(body):
        vus["body"] = body
        return {"candidates": [{"content": {"parts": [{"text": "réponse"}]}}]}

    GeminiBackend(request=faux_request).ask("Que pense Enes de Lyon ?")
    envoye = str(vus["body"])
    assert "Enes" not in envoye and "Lyon" not in envoye


def test_describe_image_scrub_la_question_mais_garde_l_image(monkeypatch):
    _anonyme(monkeypatch)
    vus = {}

    def faux_request(body):
        vus["body"] = body
        return {"candidates": [{"content": {"parts": [{"text": "une maison"}]}}]}

    GeminiBackend(request=faux_request).describe_image(b"\xff\xd8image", question="Est-ce la maison d'Enes ?")
    parts = vus["body"]["contents"][0]["parts"]
    textes = " ".join(p.get("text", "") for p in parts)
    assert "Enes" not in textes                      # la question est anonymisée
    assert any("inline_data" in p for p in parts)     # l'image, elle, est bien transmise (c'est la fonction)
