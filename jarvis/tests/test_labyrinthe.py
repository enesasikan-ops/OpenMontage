"""Tests du labyrinthe (déception + tarpit). Pas de vraie socket ni de vrai sommeil."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
import labyrinthe  # noqa: E402
from labyrinthe import Labyrinthe, PERSONAS, make_labyrinthe, tenir, zones_labyrinthe  # noqa: E402


class FakeSock:
    def __init__(self, echoue_apres=None):
        self.sends = []
        self.closed = False
        self.echoue_apres = echoue_apres

    def settimeout(self, t):
        pass

    def sendall(self, b):
        if self.echoue_apres is not None and len(self.sends) >= self.echoue_apres:
            raise OSError("connexion fermée")
        self.sends.append(b)

    def close(self):
        self.closed = True


def _horloge():
    clk = {"v": 0.0}
    return clk, (lambda s: clk.__setitem__("v", clk["v"] + s)), (lambda: clk["v"])


# --- zones ---

def test_zones_par_defaut_quand_vide():
    z = zones_labyrinthe(None)
    assert set(z) == {2223, 8081, 2121}
    assert z[2223] is PERSONAS["ssh"]


def test_zones_ignore_les_entrees_invalides():
    z = zones_labyrinthe({"2223": "ssh", "xx": "ssh", "70000": "ssh", "9000": "inconnu"})
    assert set(z) == {2223}


# --- tarpit ---

def test_tenir_piege_et_alerte_une_fois():
    _, dormir, horloge = _horloge()
    contacts = []
    sock = FakeSock()
    res = tenir(sock, ("9.9.9.9", 1234), PERSONAS["ssh"],
                on_contact=lambda ip, nom: contacts.append((ip, nom)),
                dormir=dormir, horloge=horloge, duree_max=2.0, delai=0.5)
    assert res == "tarpit"
    assert contacts == [("9.9.9.9", "faux SSH")]
    assert sock.sends and all(len(b) == 1 for b in sock.sends)   # envoi OCTET PAR OCTET
    assert sock.closed


def test_tenir_detecte_le_depart_de_l_attaquant():
    _, dormir, horloge = _horloge()
    sock = FakeSock(echoue_apres=2)             # l'attaquant coupe après 2 octets
    res = tenir(sock, ("9.9.9.9", 1), PERSONAS["ssh"],
                dormir=dormir, horloge=horloge, duree_max=100.0, delai=0.1)
    assert res == "parti" and sock.closed


def test_contact_dedupe_par_ip():
    calls = []
    lab = Labyrinthe({}, on_contact=lambda ip, nom: calls.append(ip))
    lab._contact("1.1.1.1", "x")
    lab._contact("1.1.1.1", "x")               # même IP : on piège sans re-spammer
    lab._contact("2.2.2.2", "y")
    assert calls == ["1.1.1.1", "2.2.2.2"]


# --- câblage ---

def test_make_labyrinthe_desactive(monkeypatch):
    monkeypatch.setattr(config, "LABYRINTHE", False)
    assert make_labyrinthe() is None


def test_make_labyrinthe_configure(monkeypatch):
    monkeypatch.setattr(config, "LABYRINTHE", True)
    monkeypatch.setattr(config, "LABYRINTHE_PORTS", {"2223": "ssh"})
    monkeypatch.setattr(config, "LABYRINTHE_DELAI", 1.0)
    monkeypatch.setattr(config, "LABYRINTHE_DUREE", 60.0)
    lab = make_labyrinthe(on_contact=lambda ip, nom: None)
    assert isinstance(lab, Labyrinthe) and set(lab.zones) == {2223}
