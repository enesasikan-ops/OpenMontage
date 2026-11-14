"""Le labyrinthe — transformer la maison en piège pour l'attaquant (déception défensive).

Un scanner qui balaie le réseau cherche des services à attaquer. Le labyrinthe lui en
offre PLEIN — mais tous FAUX : faux SSH, faux panneau admin, faux FTP… Dès qu'il s'y
connecte :
1. on ALERTE (personne de légitime ne touche ces leurres) et on nourrit la corrélation
   force-brute ;
2. on le PIÈGE (tarpit) : on lui envoie la bannière OCTET PAR OCTET, très lentement, et on
   tient la connexion ouverte le plus longtemps possible. Son outil attend, bloqué, pendant
   que les vrais services restent hors de vue.

Jamais offensif : on ne touche JAMAIS la machine distante, on ne fait que la faire patienter
chez soi. Bornes anti-DoS reprises du honeypot (connexions plafonnées, durée bornée). Ouvrir
des ports est un choix délibéré → opt-in (JARVIS_LABYRINTHE=1).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable

log = logging.getLogger("jarvis.labyrinthe")

DELAI_S = 1.0        # secondes entre deux octets envoyés (lent = piégeant)
DUREE_MAX_S = 120.0  # on ne retient pas une connexion au-delà (borne de ressources)
RECV_MAX = 256
MAX_CONNEXIONS = 30  # par leurre : plafond anti-saturation

PERSONAS = {
    "ssh": {"nom": "faux SSH", "banniere": b"SSH-2.0-OpenSSH_8.9p1 Ubuntu-3\r\n"},
    "http": {"nom": "faux panneau admin",
             "banniere": (b"HTTP/1.1 401 Unauthorized\r\nServer: Apache/2.4.52 (Ubuntu)\r\n"
                          b"WWW-Authenticate: Basic realm=\"Routeur Admin\"\r\n\r\n")},
    "ftp": {"nom": "faux FTP", "banniere": b"220 ProFTPD 1.3.7 Server ready.\r\n"},
    "telnet": {"nom": "faux Telnet", "banniere": b"\r\nrouteur login: "},
    "mysql": {"nom": "fausse base MySQL", "banniere": b"J\x00\x00\x00\n5.7.38-0ubuntu0.1\x00"},
}
DEFAUT_PORTS = {"2223": "ssh", "8081": "http", "2121": "ftp"}


def zones_labyrinthe(ports: "dict | None") -> dict:
    """Associe un numéro de port à un persona de leurre. Ignore ports/kinds invalides."""
    out = {}
    for port, kind in (ports or DEFAUT_PORTS).items():
        try:
            p = int(port)
        except (TypeError, ValueError):
            continue
        persona = PERSONAS.get(str(kind).lower())
        if persona and 0 < p < 65536:
            out[p] = persona
    return out


def tenir(sock, adresse, persona: dict, on_contact: "Callable[[str, str], None] | None" = None,
          dormir: Callable[[float], None] = time.sleep, horloge: Callable[[], float] = time.monotonic,
          duree_max: float = DUREE_MAX_S, delai: float = DELAI_S) -> str:
    """Tarpit : alerte une fois, puis débite la bannière octet par octet pour retenir l'intrus.

    Renvoie 'parti' si l'attaquant lâche, 'tarpit' si on l'a tenu jusqu'à la borne de durée.
    """
    ip = adresse[0] if adresse else "?"
    try:
        sock.settimeout(max(1.0, delai * 4))
    except OSError:
        pass
    if on_contact is not None:
        try:
            on_contact(ip, persona.get("nom", "leurre"))
        except Exception:
            log.exception("alerte labyrinthe")
    debut = horloge()
    banniere = persona.get("banniere", b"") or b""
    try:
        for i in range(len(banniere)):
            sock.sendall(banniere[i:i + 1])        # un octet à la fois : l'outil distant attend
            dormir(delai)
            if horloge() - debut >= duree_max:
                return "tarpit"
        n = 0
        while horloge() - debut < duree_max and n < 100000:
            sock.sendall(b"\r\n")                   # on continue de le faire patienter
            dormir(delai)
            n += 1
        return "tarpit"
    except OSError:
        return "parti"
    finally:
        try:
            sock.close()
        except OSError:
            pass


class Labyrinthe:
    def __init__(self, zones: dict, on_contact: "Callable[[str, str], None] | None" = None,
                 host: str = "0.0.0.0", delai: float = DELAI_S, duree_max: float = DUREE_MAX_S,
                 max_connexions: int = MAX_CONNEXIONS):
        self.zones = zones                          # {port: persona}
        self.on_contact = on_contact
        self.host = host
        self.delai = delai
        self.duree_max = duree_max
        self.max_connexions = max_connexions
        self._halt = threading.Event()
        self._serveurs: list = []
        self._vus: set = set()                      # 1 alerte par IP (le tarpit, lui, agit toujours)

    def _contact(self, ip: str, nom: str) -> None:
        if ip in self._vus:                         # déjà signalé : on piège sans re-spammer
            return
        self._vus.add(ip)
        if self.on_contact is not None:
            self.on_contact(ip, nom)

    def demarrer(self) -> dict:
        ouverts = []
        for port, persona in self.zones.items():
            s = self._ouvrir(port)
            if s is not None:
                self._serveurs.append(s)
                places = threading.Semaphore(self.max_connexions)
                threading.Thread(target=self._boucle, args=(s, persona, places),
                                 name=f"jarvis-labyrinthe-{port}", daemon=True).start()
                ouverts.append(port)
        return {"statut": "succès" if ouverts else "erreur", "ports": ouverts}

    def _ouvrir(self, port: int) -> "socket.socket | None":
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, port))
            s.listen(16)
            s.settimeout(1.0)
            return s
        except OSError as exc:
            log.warning("labyrinthe : port %d indisponible (%s)", port, exc)
            return None

    def _boucle(self, serveur, persona, places) -> None:
        while not self._halt.is_set():
            try:
                client, adresse = serveur.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not places.acquire(blocking=False):   # trop de connexions : on lâche (anti-DoS)
                try:
                    client.close()
                except OSError:
                    pass
                continue
            threading.Thread(target=self._traiter, args=(client, adresse, persona, places),
                             daemon=True).start()

    def _traiter(self, client, adresse, persona, places) -> None:
        try:
            tenir(client, adresse, persona, on_contact=self._contact,
                  delai=self.delai, duree_max=self.duree_max)
        finally:
            places.release()

    def arreter(self) -> None:
        self._halt.set()
        for s in self._serveurs:
            try:
                s.close()
            except OSError:
                pass


def make_labyrinthe(on_contact: "Callable[[str, str], None] | None" = None) -> "Labyrinthe | None":
    import config
    if not getattr(config, "LABYRINTHE", False):
        return None
    zones = zones_labyrinthe(getattr(config, "LABYRINTHE_PORTS", None))
    if not zones:
        return None
    return Labyrinthe(zones, on_contact=on_contact,
                      delai=getattr(config, "LABYRINTHE_DELAI", DELAI_S),
                      duree_max=getattr(config, "LABYRINTHE_DUREE", DUREE_MAX_S))
