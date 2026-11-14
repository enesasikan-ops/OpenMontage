"""Tests du pot de miel : capture sûre, anti-injection, anti-saturation."""

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from honeypot import Honeypot, _assainir, gerer_intrus  # noqa: E402


class FauxSocket:
    def __init__(self, entrees):
        self.entrees = list(entrees)
        self.envoye = b""
        self.timeout = None
        self.ferme = False

    def settimeout(self, t):
        self.timeout = t

    def sendall(self, b):
        self.envoye += b

    def recv(self, n):
        return self.entrees.pop(0) if self.entrees else b""

    def close(self):
        self.ferme = True


# --- Nettoyage anti-injection ---

def test_assainir_retire_les_sauts_de_ligne():
    assert "\n" not in _assainir("secret\n2026 root: connecté")
    assert _assainir("ab\x00c\x1b") == "ab?c?"


# --- Dialogue leurre ---

def test_capture_identifiant_et_mot_de_passe():
    vus = []
    s = FauxSocket([b"admin\n", b"motdepasse\n"])
    gerer_intrus(s, ("1.2.3.4", 55000), lambda ip, u, p: vus.append((ip, u, p)))
    assert vus == [("1.2.3.4", "admin", "motdepasse")]
    assert s.timeout is not None      # un délai d'attente est posé (anti-blocage)
    assert s.ferme                    # la connexion est bien fermée


def test_injection_de_log_neutralisee():
    vus = []
    s = FauxSocket([b"admin\n", b"x\n2026 FAUX LOG root OK\n"])
    gerer_intrus(s, ("1.2.3.4", 1), lambda ip, u, p: vus.append(p))
    assert "\n" not in vus[0]         # la fausse ligne ne peut plus être injectée


def test_sans_callback_ne_plante_pas():
    s = FauxSocket([b"a\n", b"b\n"])
    gerer_intrus(s, ("1.2.3.4", 1), None)   # aucun on_intrusion
    assert s.ferme


def test_recv_qui_expire_ne_plante_pas():
    class SocketLent(FauxSocket):
        def recv(self, n):
            raise socket.timeout()
    s = SocketLent([])
    gerer_intrus(s, ("1.2.3.4", 1), lambda *a: None)   # ne doit pas lever
    assert s.ferme


# --- Bout en bout sur une vraie socket ---

def test_bout_en_bout_capture_une_connexion():
    vus = []
    hp = Honeypot(on_intrusion=lambda ip, u, p: vus.append((u, p)), port=0, host="127.0.0.1")
    assert hp.demarrer()["statut"] == "succès"
    try:
        port = hp._serveur.getsockname()[1]
        c = socket.create_connection(("127.0.0.1", port), timeout=3)
        time.sleep(0.2)
        c.recv(500)
        c.sendall(b"pirate\n")
        time.sleep(0.2)
        c.recv(500)
        c.sendall(b"1234\n")
        for _ in range(50):
            if vus:
                break
            time.sleep(0.05)
        c.close()
        assert vus == [("pirate", "1234")]
    finally:
        hp.arreter()
