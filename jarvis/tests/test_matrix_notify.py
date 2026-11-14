"""Tests du canal de commandement Matrix (envoi d'alertes sur ton serveur chiffré)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from matrix_notify import MatrixNotifier, _type_media, make_matrix_notifier  # noqa: E402


def _notifier(envois):
    return MatrixNotifier("https://matrix.maison.fr/", "jeton", "!salon:maison.fr",
                          user="@jarvis:maison.fr", envoi=lambda t, c: envois.append((t, c)))


def test_type_media():
    assert _type_media("clip.mp4") == "m.video"
    assert _type_media("photo.jpg") == "m.image"
    assert _type_media("rapport.pdf") == "m.file"


def test_envoyer_texte():
    envois = []
    assert _notifier(envois).envoyer("🚨 Intrusion détectée") is True
    assert envois == [("🚨 Intrusion détectée", None)]


def test_envoyer_media():
    envois = []
    _notifier(envois).envoyer("Intrus au porche", chemin="/tmp/clip.mp4")
    assert envois == [("Intrus au porche", "/tmp/clip.mp4")]


def test_non_configure_renvoie_false():
    n = MatrixNotifier("", "", "", envoi=lambda t, c: None)
    assert n.configure is False and n.envoyer("x") is False


def test_echec_envoi_ne_leve_pas():
    def boom(t, c):
        raise OSError("serveur injoignable")
    n = MatrixNotifier("https://m.fr", "j", "!s:m.fr", envoi=boom)
    assert n.envoyer("x") is False            # pas de crash : repli silencieux


def test_serveur_normalise():
    assert _notifier([]).serveur == "https://matrix.maison.fr"   # pas de / final


# --- Fabrique ---

def test_make_desactive(monkeypatch):
    monkeypatch.setattr(config, "MATRIX", False)
    assert make_matrix_notifier() is None


def test_make_incomplet(monkeypatch):
    monkeypatch.setattr(config, "MATRIX", True)
    monkeypatch.setattr(config, "MATRIX_SERVEUR", "https://m.fr")
    monkeypatch.setattr(config, "MATRIX_JETON", "")        # jeton manquant
    monkeypatch.setattr(config, "MATRIX_SALON", "!s:m.fr")
    monkeypatch.setattr(config, "MATRIX_USER", "")
    assert make_matrix_notifier() is None


def test_make_pret(monkeypatch):
    monkeypatch.setattr(config, "MATRIX", True)
    monkeypatch.setattr(config, "MATRIX_SERVEUR", "https://m.fr")
    monkeypatch.setattr(config, "MATRIX_JETON", "jeton")
    monkeypatch.setattr(config, "MATRIX_SALON", "!s:m.fr")
    monkeypatch.setattr(config, "MATRIX_USER", "@jarvis:m.fr")
    n = make_matrix_notifier()
    assert n is not None and n.configure
