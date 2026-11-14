"""Détection d'exfiltration — repérer une machine qui « appelle la maison » d'un intrus.

Après une compromission, un code malveillant ouvre souvent une connexion SORTANTE vers un
serveur de commande (C2) ou pour voler des données. Ce module liste les destinations
sortantes ÉTABLIES (hôtes publics) et alerte sur une destination NOUVELLE, inconnue de la
référence — exactement comme la détection de persistance, côté réseau.

Ligne tenue : lecture seule + alerte. Honnêteté : c'est le veilleur le plus BAVARD (toute
nouvelle destination légitime — un site, un service cloud — apparaît aussi). D'où le
fonctionnement par référence : 1re photo = destinations de confiance ; ensuite, après une
nouveauté légitime, tu « acceptes l'exfiltration » (rebase). Une liste blanche (préfixes IP)
réduit encore le bruit.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Callable, Iterator

from netguard import _ip_interne

log = logging.getLogger("jarvis.exfilwatch")

_ADDR = re.compile(r"(\[[0-9A-Fa-f:]+\]|\d{1,3}(?:\.\d{1,3}){3}|\*):\d+")


def _ss_reel() -> str:
    for args in (["ss", "-Htn", "state", "established"], ["ss", "-tn", "state", "established"]):
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                return r.stdout
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _ip(token: str) -> str:
    return token.strip("[]")


def hotes_distants(texte: str, est_interne: Callable[[str], bool] = _ip_interne) -> set:
    """Extrait les IP distantes PUBLIQUES des connexions établies (2ᵉ adresse de chaque ligne)."""
    hotes = set()
    for ligne in (texte or "").splitlines():
        adresses = _ADDR.findall(ligne)
        if len(adresses) < 2:
            continue
        pair = _ip(adresses[1])
        if pair == "*" or not pair:
            continue
        try:
            if est_interne(pair):            # on ignore le LAN : seul le trafic vers l'extérieur compte
                continue
        except ValueError:
            continue
        hotes.add(pair)
    return hotes


def _blanc(hote: str, liste_blanche) -> bool:
    return any(hote == p or hote.startswith(p) for p in liste_blanche)


class Collecteur:
    def __init__(self, run_ss: Callable[[], str] = _ss_reel, liste_blanche=()):
        self.run_ss = run_ss
        self.liste_blanche = tuple(liste_blanche)

    def instantane(self) -> dict:
        hotes = {h for h in hotes_distants(self.run_ss()) if not _blanc(h, self.liste_blanche)}
        return {"hotes": sorted(hotes)}


def comparer(base: dict, actuel: dict) -> "Iterator[tuple[bool, str]]":
    avant, apres = set(base.get("hotes", [])), set(actuel.get("hotes", []))
    for hote in sorted(apres - avant):
        yield False, f"📡 Nouvelle destination sortante : {hote} (connexion inattendue ?)"


class ExfilMonitor:
    def __init__(self, collecteur: Collecteur, store):
        self.collecteur = collecteur
        self.store = store

    def check(self) -> list:
        actuel = self.collecteur.instantane()
        base = self.store.data.get("base")
        if base is None:
            self.store.data["base"] = actuel
            self.store.save()
            return []
        return list(comparer(base, actuel))

    def rapport(self) -> str:
        actuel = self.collecteur.instantane()
        base = self.store.data.get("base")
        if base is None:
            self.store.data["base"] = actuel
            self.store.save()
            return "Référence des destinations sortantes établie. RAS pour l'instant."
        nouvelles = [m for _, m in comparer(base, actuel)]
        if not nouvelles:
            return "Trafic sortant : RAS — aucune destination externe inconnue."
        return "⚠️ Destinations sortantes inconnues :\n" + "\n".join(f"- {m}" for m in nouvelles)

    def accepter(self) -> str:
        self.store.data["base"] = self.collecteur.instantane()
        self.store.save()
        return "✅ Destinations sortantes actuelles acceptées comme référence."


_MONITOR: "ExfilMonitor | None" = None


def _monitor() -> ExfilMonitor:
    global _MONITOR
    if _MONITOR is None:
        import config
        from skills import JsonStore
        liste = getattr(config, "EXFIL_ALLOW", ())
        _MONITOR = ExfilMonitor(Collecteur(liste_blanche=liste), JsonStore(config.EXFIL_FILE, {}))
    return _MONITOR


def make_exfil_monitor() -> "ExfilMonitor | None":
    import config
    return _monitor() if getattr(config, "EXFIL", False) else None


def build_exfil_tools() -> list:
    import config
    from tools import Tool

    if not getattr(config, "EXFIL", False):
        return []
    mon = _monitor()
    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="verifier_exfiltration",
             description=("Vérifie le trafic SORTANT : y a-t-il une destination externe inconnue "
                          "(signe d'un code qui « appelle la maison » / vol de données) ? "
                          "« des connexions sortantes bizarres ? »."),
             parameters=vide, run=lambda: mon.rapport()),
        Tool(name="accepter_exfiltration",
             description="Accepte les destinations sortantes actuelles comme référence (après vérif).",
             parameters=vide, run=lambda: mon.accepter(),
             confirm=lambda: ("Je prends les destinations sortantes actuelles comme référence : "
                              "les alertes en cours seront effacées. Tu confirmes ?")),
    ]
