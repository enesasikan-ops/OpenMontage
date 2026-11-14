"""Blocage d'IP au pare-feu — défensif, confirmé, jamais offensif.

Riposte propre à une intrusion : bloquer une IP d'attaquant sur TON pare-feu (elle ne peut
plus t'atteindre). Ce n'est PAS une contre-attaque : on ne touche jamais à la machine
distante, on ferme juste sa porte chez soi.

Garde-fous :
- jamais d'IP interne / privée / passerelle (sinon tu te coupes toi-même) ;
- une liste blanche d'IP à ne jamais bloquer (DNS, services que tu utilises) ;
- une IP source peut être USURPÉE : le blocage se fait sur ta décision (commande
  « bloque <ip> » après l'alerte), pas en automatique et aveugle ;
- réversible : « débloque <ip> ». La liste est persistée.

L'application réelle au pare-feu demande les droits root (iptables) ou admin (netsh) ;
la fonction d'application est injectable (pour les tests) et à activer sur la vraie machine.
"""

from __future__ import annotations

import ipaddress
import logging
import platform
import subprocess
from pathlib import Path
from typing import Callable

from netguard import _ip_interne
from skills import JsonStore

log = logging.getLogger(__name__)


def _cmd_bloquer(ip: str) -> list[str]:
    if platform.system() == "Windows":
        return ["netsh", "advfirewall", "firewall", "add", "rule",
                f"name=jarvis-block-{ip}", "dir=in", "action=block", f"remoteip={ip}"]
    return ["iptables", "-A", "INPUT", "-s", ip, "-j", "DROP"]


def _cmd_debloquer(ip: str) -> list[str]:
    if platform.system() == "Windows":
        return ["netsh", "advfirewall", "firewall", "delete", "rule", f"name=jarvis-block-{ip}"]
    return ["iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"]


def _executer(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, timeout=15)


class IpBlocker:
    def __init__(self, path: Path, appliquer: "Callable[[str], None] | None" = None,
                 retirer: "Callable[[str], None] | None" = None, liste_blanche=()):
        self.store = JsonStore(path, {"bloquees": []})
        self.store.data.setdefault("bloquees", [])
        self.appliquer = appliquer or (lambda ip: _executer(_cmd_bloquer(ip)))
        self.retirer = retirer or (lambda ip: _executer(_cmd_debloquer(ip)))
        self.liste_blanche = set(liste_blanche)

    def _valider(self, ip: str) -> None:
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            raise ValueError(f"« {ip} » n'est pas une adresse IP valide.")
        if ip in self.liste_blanche:
            raise ValueError(f"{ip} est protégée (liste blanche) : je ne la bloque pas.")
        if _ip_interne(ip):
            raise ValueError(f"{ip} est une adresse interne/privée : bloquer son propre réseau se retournerait contre soi.")

    def bloquer(self, ip: str) -> str:
        ip = (ip or "").strip()
        self._valider(ip)
        if ip in self.store.data["bloquees"]:
            return f"{ip} est déjà bloquée."
        try:
            self.appliquer(ip)
        except Exception as exc:
            return f"Blocage impossible (droits pare-feu ?) : {exc}"
        self.store.data["bloquees"].append(ip)
        self.store.save()
        return f"🛡️ {ip} bloquée au pare-feu. Réversible avec « débloque {ip} »."

    def debloquer(self, ip: str) -> str:
        ip = (ip or "").strip()
        if ip not in self.store.data["bloquees"]:
            return f"{ip} n'est pas dans la liste des bloquées."
        try:
            self.retirer(ip)
        except Exception as exc:
            return f"Déblocage impossible : {exc}"
        self.store.data["bloquees"].remove(ip)
        self.store.save()
        return f"{ip} débloquée."

    def liste(self) -> list[str]:
        return list(self.store.data["bloquees"])
