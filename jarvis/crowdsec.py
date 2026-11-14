"""Pont vers CrowdSec (IDS/IPS réseau open-source), en local.

CrowdSec surveille les connexions réseau (SSH, web, Wi-Fi…) et **bloque** les IP
hostiles via ses « bouncers ». Jarvis interroge son API locale (LAPI) en **lecture
seule** et t'annonce, honnêtement, chaque IP *nouvellement* bloquée :

  « Monsieur, une tentative d'intrusion réseau en provenance d'une IP externe a été
   détectée et bloquée. Les protocoles de sécurité sont maintenus. »

Jarvis ne bloque rien lui-même ici : CrowdSec l'a déjà fait, Jarvis **rapporte**. On
reste sur TON réseau, sur TA LAPI : aucune donnée ne part à l'extérieur.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import urllib.request
from typing import Callable

import config

log = logging.getLogger(__name__)

TIMEOUT_S = 5

# Traduction des scénarios CrowdSec les plus courants en français lisible.
_RAISONS = (
    ("ssh-slow-bf", "force brute SSH (lente)"),
    ("ssh-bf", "force brute SSH"),
    ("http-bf", "force brute web"),
    ("http-probing", "sondage web"),
    ("http-crawl", "balayage web"),
    ("http-sensitive-files", "accès à des fichiers sensibles"),
    ("http-path-traversal", "traversée de chemin web"),
    ("port-scan", "balayage de ports"),
    ("bruteforce", "force brute"),
)


def _raison(scenario: str) -> str:
    s = (scenario or "").lower()
    for cle, txt in _RAISONS:
        if cle in s:
            return txt
    return scenario.split("/")[-1] if scenario else "activité hostile"


def _portee(ip: str) -> str:
    try:
        return "externe" if ipaddress.ip_address(ip).is_global else "locale"
    except ValueError:
        return "externe"


def _texte(d: dict) -> str:
    ip = d.get("value", "?")
    return (f"tentative d'intrusion réseau en provenance de {ip} ({_portee(ip)}) "
            f"détectée et bloquée ({_raison(d.get('scenario', ''))}). "
            f"Les protocoles de sécurité sont maintenus.")


def _cle(d: dict):
    return d.get("id") or (d.get("value"), d.get("type"), d.get("scenario"), d.get("origin"))


# Origine « locale » = CrowdSec a détecté une VRAIE attaque sur TON réseau (ou toi, manuel).
# Les autres (CAPI, blocklists communautaires/premium) sont du blocage PRÉVENTIF : il ne faut
# pas les annoncer une par une (des milliers d'IP du « bouclier de meute » te noieraient).
_ORIGINES_LOCALES = {"crowdsec", "cscli"}


def _locale(d: dict) -> bool:
    return str(d.get("origin", "crowdsec")).strip().lower() in _ORIGINES_LOCALES


class CrowdSec:
    """Client minimal de la LAPI CrowdSec : les décisions actives = les IP bloquées."""

    def __init__(self, url: str, api_key: str, get: "Callable | None" = None):
        self.url = (url or "").rstrip("/")
        self.api_key = api_key
        self._get = get or self._http_get

    def _http_get(self, url: str, headers: dict) -> list:
        req = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # LAN : jamais de proxy
        with opener.open(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read().decode("utf-8") or "null")
        return data or []

    def decisions(self) -> list:
        return self._get(f"{self.url}/v1/decisions", {"X-Api-Key": self.api_key})


class CrowdSecWatcher:
    """Checker branché dans SecurityWatcher : renvoie les IP NOUVELLEMENT bloquées.

    Au premier passage, on mémorise le passif sans l'annoncer (pas de rafale au
    démarrage) ; ensuite, seules les nouvelles décisions sont signalées. Les décisions
    expirées sont oubliées, de sorte qu'un nouveau blocage de la même IP est réannoncé.
    """

    def __init__(self, client: CrowdSec):
        self.client = client
        self._vus: "set | None" = None

    def check(self) -> "list[tuple[bool, str]]":
        try:
            decisions = self.client.decisions()
        except Exception as exc:
            log.warning("CrowdSec injoignable : %s", exc)
            return []
        presentes = {_cle(d) for d in decisions}
        if self._vus is None:            # premier passage : on apprend sans annoncer
            self._vus = presentes
            return []
        # On n'ANNONCE que les attaques LOCALES (réelles, sur ton réseau). Les décisions
        # préventives de la meute sont suivies mais pas criées une par une (anti-rafale).
        nouvelles = [(True, _texte(d)) for d in decisions
                     if _cle(d) not in self._vus and _locale(d)]
        self._vus = presentes
        return nouvelles


def make_crowdsec() -> "CrowdSecWatcher | None":
    """Construit le checker CrowdSec depuis la config, ou None s'il n'est pas prêt."""
    if not config.CROWDSEC:
        return None
    if not config.CROWDSEC_KEY:
        log.warning("CrowdSec activé mais JARVIS_CROWDSEC_CLE manquante : surveillance inactive.")
        return None
    return CrowdSecWatcher(CrowdSec(config.CROWDSEC_URL, config.CROWDSEC_KEY))


def build_crowdsec_tools(client: "CrowdSec | None" = None) -> list:
    """Outil (lecture seule) pour demander l'état des blocages réseau."""
    from tools import Tool

    if not (config.CROWDSEC and config.CROWDSEC_KEY):
        return []
    client = client or CrowdSec(config.CROWDSEC_URL, config.CROWDSEC_KEY)

    def rapport() -> str:
        try:
            decisions = client.decisions()
        except Exception:
            return "Je n'arrive pas à joindre CrowdSec pour l'instant."
        if not decisions:
            return "Aucune IP bloquée pour le moment : le réseau est calme."
        locales = [d for d in decisions if _locale(d)]
        communaute = len(decisions) - len(locales)
        parts = []
        if locales:
            apercu = " ; ".join(f"{d.get('value', '?')} ({_raison(d.get('scenario', ''))})"
                                for d in locales[:5])
            reste = f" (et {len(locales) - 5} autres)" if len(locales) > 5 else ""
            parts.append(f"{len(locales)} attaque(s) directe(s) sur votre réseau, bloquée(s) : {apercu}{reste}")
        else:
            parts.append("Aucune attaque directe sur votre réseau")
        if communaute:
            parts.append(f"bouclier communautaire : {communaute} IP bloquées préventivement "
                         "(immunité de meute, avant même qu'elles vous visent)")
        return ". ".join(parts) + "."

    return [Tool(
        name="point_securite_reseau",
        description=("Fait le point sur les intrusions réseau bloquées par CrowdSec "
                     "(IP bannies actives). À utiliser pour « des intrusions ? », "
                     "« qui est bloqué ? », « point sécurité réseau »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=rapport,
    )]
