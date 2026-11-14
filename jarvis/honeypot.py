"""Pot de miel (honeypot) : un faux serveur pour détecter les intrus sur TON réseau.

Principe : un service leurre (ex. un faux SSH) que personne de légitime n'utilise. Toute
connexion est donc suspecte : on note l'IP et ce qui est tenté, puis on t'alerte.

Sécurité (le honeypot est la pièce la PLUS exposée, il doit être le moins privilégié) :
- il n'a AUCUN accès au cœur de Jarvis ni à l'exécution de code : juste un callback
  `on_intrusion(ip, identifiant, mot_de_passe)` qui enregistre et alerte ;
- délai d'attente + nombre de connexions plafonné : il ne peut pas être noyé (déni de service) ;
- les données reçues sont nettoyées avant d'être journalisées (pas d'injection de log) ;
- riposte = preuve + alerte. Un blocage d'IP reste une action DÉFENSIVE proposée et
  confirmée (jamais de contre-attaque : le « hack back » est illégal, et l'IP peut être usurpée).
"""

from __future__ import annotations

import logging
import re
import socket
import threading
from typing import Callable

log = logging.getLogger(__name__)

BANNIERE = b"Ubuntu 22.04.3 LTS\r\nserveur-domotique login: "
TIMEOUT_S = 10.0
MAX_CONNEXIONS = 20
RECV_MAX = 512

_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _assainir(texte: str) -> str:
    """Retire les caractères de contrôle (sauts de ligne compris) : anti-injection de log."""
    return _CTRL.sub("?", texte)[:200]


def gerer_intrus(sock, adresse, on_intrusion: "Callable[[str, str, str], None] | None") -> None:
    """Dialogue leurre avec une connexion suspecte. `sock` doit supporter settimeout/recv/send/close."""
    ip = adresse[0] if adresse else "?"
    try:
        sock.settimeout(TIMEOUT_S)                     # un client lent est lâché, pas gardé
        sock.sendall(BANNIERE)
        identifiant = _assainir(sock.recv(RECV_MAX).decode("utf-8", "ignore").strip())
        sock.sendall(b"\r\nPassword: ")
        mot_de_passe = _assainir(sock.recv(RECV_MAX).decode("utf-8", "ignore").strip())
        log.warning("Honeypot touché depuis %s — user=%r pass=%r", ip, identifiant, mot_de_passe)
        try:
            sock.sendall(b"\r\nLogin incorrect.\r\n")
        except OSError:
            pass
        if on_intrusion is not None:
            on_intrusion(ip, identifiant, mot_de_passe)   # enregistre + alerte, rien de plus
    except (OSError, socket.timeout):
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


class Honeypot:
    def __init__(self, on_intrusion: "Callable[[str, str, str], None] | None" = None,
                 port: int = 2222, host: str = "0.0.0.0",
                 max_connexions: int = MAX_CONNEXIONS):
        self.on_intrusion = on_intrusion
        self.port = port
        self.host = host
        self._places = threading.Semaphore(max_connexions)   # plafond anti-saturation
        self._serveur: "socket.socket | None" = None
        self._halt = threading.Event()

    def demarrer(self) -> dict:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((self.host, self.port))
            s.listen(16)
            s.settimeout(1.0)                 # pour pouvoir s'arrêter proprement
        except OSError as exc:
            return {"statut": "erreur", "message": f"Impossible de lancer le honeypot : {exc}"}
        self._serveur = s
        threading.Thread(target=self._boucle, name="jarvis-honeypot", daemon=True).start()
        log.info("🍯 Honeypot à l'écoute sur %s:%d", self.host, self.port)
        return {"statut": "succès", "message": f"Honeypot déployé sur le port {self.port}"}

    def _boucle(self) -> None:
        while not self._halt.is_set():
            try:
                client, adresse = self._serveur.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if not self._places.acquire(blocking=False):   # trop de connexions : on lâche
                try:
                    client.close()
                except OSError:
                    pass
                continue
            threading.Thread(target=self._traiter, args=(client, adresse), daemon=True).start()

    def _traiter(self, client, adresse) -> None:
        try:
            gerer_intrus(client, adresse, self.on_intrusion)
        finally:
            self._places.release()

    def arreter(self) -> None:
        self._halt.set()
        if self._serveur is not None:
            try:
                self._serveur.close()
            except OSError:
                pass
