"""Tests de la passerelle lunettes connectées (image -> texte court sur le verre)."""

import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from glasses import (GlassesVision, make_server, question_lunettes,  # noqa: E402
                     reponse_courte, sur_de_demarrer)


# --- Helpers de texte ---

def test_reponse_courte_laisse_court():
    assert reponse_courte("C'est le filtre à huile.") == "C'est le filtre à huile."


def test_reponse_courte_tronque_proprement():
    long = "Ceci est une très longue description " + "mot " * 60
    out = reponse_courte(long, max_car=40)
    assert len(out) <= 41 and out.endswith("…") and "  " not in out


def test_reponse_courte_vide():
    assert reponse_courte("") == "" and reponse_courte(None) == ""


def test_question_defaut_et_personnalisee():
    assert "objet" in question_lunettes("")
    q = question_lunettes("quelle est cette pièce")
    assert "quelle est cette pièce" in q and "courte" in q


# --- Analyse ---

def test_analyser_appelle_la_vision():
    recu = {}

    def describe(image, question):
        recu["image"], recu["question"] = image, question
        return "C'est le filtre à huile, Monsieur, en bon état apparent."

    out = GlassesVision(describe).analyser(b"\xff\xd8jpeg", "quelle est cette pièce")
    assert recu["image"] == b"\xff\xd8jpeg"
    assert "cette pièce" in recu["question"]
    assert out.startswith("C'est le filtre à huile")


def test_analyser_sans_image():
    assert GlassesVision(lambda i, q: "x").analyser(b"") == "Je n'ai pas reçu d'image."


def test_analyser_sans_vision():
    assert "pas configurée" in GlassesVision(None).analyser(b"img")


def test_analyser_vision_en_panne():
    def boom(image, question):
        raise RuntimeError("modèle absent")
    assert "impossible" in GlassesVision(boom).analyser(b"img")


# --- Garde-fou de démarrage ---

def test_sur_de_demarrer_local_sans_jeton():
    assert sur_de_demarrer("127.0.0.1", "") is None


def test_refuse_reseau_sans_jeton():
    assert "refusé" in sur_de_demarrer("0.0.0.0", "")


def test_reseau_avec_jeton_ok():
    assert sur_de_demarrer("0.0.0.0", "secret") is None


# --- Service HTTP (serveur réel sur un port éphémère) ---

@pytest.fixture
def serveur():
    vision = GlassesVision(lambda image, question: f"vu {len(image)} octets : filtre à huile")
    srv = make_server(vision, "127.0.0.1", 0, token="")
    import threading
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, srv.server_address[1]
    srv.shutdown()


def _post(port, chemin, corps=b"", methode="POST"):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{chemin}", data=corps, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def test_voir_renvoie_le_texte(serveur):
    _, port = serveur
    code, texte = _post(port, "/voir?q=quelle+piece", b"\xff\xd8image")
    assert code == 200 and "filtre à huile" in texte


def test_voir_sans_image(serveur):
    _, port = serveur
    code, _ = _post(port, "/voir", b"")
    assert code == 400


def test_sante_sans_jeton(serveur):
    _, port = serveur
    code, texte = _post(port, "/sante", methode="GET")
    assert code == 200 and texte == "ok"


def test_chemin_inconnu(serveur):
    _, port = serveur
    code, _ = _post(port, "/autre", b"x")
    assert code == 404


# --- Service avec jeton ---

@pytest.fixture
def serveur_protege():
    vision = GlassesVision(lambda image, question: "ok")
    srv = make_server(vision, "127.0.0.1", 0, token="secret")
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def test_refuse_sans_jeton(serveur_protege):
    code, _ = _post(serveur_protege, "/voir", b"\xff\xd8x")
    assert code == 401


def test_accepte_bon_jeton(serveur_protege):
    code, texte = _post(serveur_protege, "/voir?jeton=secret", b"\xff\xd8x")
    assert code == 200 and texte == "ok"


def test_refuse_mauvais_jeton(serveur_protege):
    code, _ = _post(serveur_protege, "/voir?jeton=faux", b"\xff\xd8x")
    assert code == 401
