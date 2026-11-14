"""Audit de posture réseau — trouver les failles SANS les exploiter.

On refuse l'« agent offensif » (écrire des exploits, pirater, pivoter : c'est du malware
autonome, dangereux pour tes propres appareils et retournable par injection). On garde le
résultat utile : un scan NON DESTRUCTIF qui liste les appareils, leurs ports/services
exposés et les firmwares périmés, puis signale les risques connus avec la remédiation.

On DÉTECTE une porte ouverte ; on ne la défonce pas. Complète la Sentinelle (changements)
et CrowdSec (attaques en cours) par l'évaluation de la posture (ce qui est exposé avant
qu'on attaque). Les actions (isoler un appareil, couper son Internet) restent proposées,
jamais menées en douce.
"""

from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("jarvis.audit")

GRAVITES = {"critique": 3, "haute": 2, "moyenne": 1, "basse": 0}

# Ports/services exposés et risque DÉFENSIF connu (aucun exploit, juste du savoir public).
PORTS_RISQUE = {
    23: ("critique", "Telnet ouvert (trafic en clair, identifiants souvent par défaut)",
         "Désactive Telnet, isole l'appareil."),
    21: ("haute", "FTP ouvert (identifiants et fichiers en clair)",
         "Désactive FTP ou passe en SFTP."),
    445: ("haute", "Partage SMB exposé",
          "Restreins SMB au réseau de confiance."),
    3389: ("haute", "Bureau à distance (RDP) exposé",
           "Ferme RDP côté réseau, VPN uniquement."),
    1900: ("moyenne", "UPnP exposé (élargit la surface d'attaque)",
           "Désactive UPnP sur le routeur et l'appareil."),
    80: ("moyenne", "Administration HTTP non chiffrée",
         "Change le mot de passe par défaut, coupe l'accès Internet de l'appareil."),
}


def evaluer_appareil(appareil: dict) -> list:
    """Constats pour un appareil {ip, mac, nom, ports:[{port,service?}], firmware_obsolete?}."""
    nom = appareil.get("nom") or appareil.get("ip") or appareil.get("mac") or "appareil inconnu"
    constats = []
    for p in appareil.get("ports", []):
        num = p.get("port") if isinstance(p, dict) else p
        if num in PORTS_RISQUE:
            gravite, probleme, conseil = PORTS_RISQUE[num]
            constats.append({"appareil": nom, "gravite": gravite,
                             "probleme": probleme, "conseil": conseil})
    if appareil.get("firmware_obsolete"):
        constats.append({"appareil": nom, "gravite": "haute",
                         "probleme": "Firmware obsolète (failles publiques possibles)",
                         "conseil": "Mets à jour le firmware ; en attendant, isole l'appareil."})
    if appareil.get("identifiants_par_defaut"):
        constats.append({"appareil": nom, "gravite": "critique",
                         "probleme": "Identifiants par défaut probables",
                         "conseil": "Change immédiatement le mot de passe par défaut."})
    return constats


def evaluer_reseau(appareils: list) -> list:
    constats = []
    for a in appareils:
        constats += evaluer_appareil(a)
    constats.sort(key=lambda c: GRAVITES.get(c["gravite"], 0), reverse=True)
    return constats


def rapport(constats: list) -> str:
    if not constats:
        return "Audit réseau : rien de notable. Aucune exposition risquée repérée."
    lignes = [f"Audit réseau — {len(constats)} point(s) d'attention :"]
    for c in constats[:10]:
        lignes.append(f"  • [{c['gravite']}] {c['appareil']} : {c['probleme']} → {c['conseil']}")
    lignes.append("\nJe peux isoler un appareil au pare-feu si vous le demandez (je n'agis pas seul).")
    return "\n".join(lignes)


def _scan_nmap(reseau: str) -> list:
    """Scan NON destructif (découverte + versions) via nmap. Aucun exploit."""
    import shutil
    import subprocess
    import xml.etree.ElementTree as ET

    if shutil.which("nmap") is None:
        raise RuntimeError("nmap n'est pas installé (apt install nmap).")
    out = subprocess.run(["nmap", "-sV", "-T4", "-oX", "-", reseau],
                         capture_output=True, text=True, timeout=600, check=False).stdout
    appareils = []
    for host in ET.fromstring(out).findall("host"):
        adr = {a.get("addrtype"): a.get("addr") for a in host.findall("address")}
        ports = []
        for port in host.findall("./ports/port"):
            etat = port.find("state")
            if etat is not None and etat.get("state") == "open":
                ports.append({"port": int(port.get("portid")),
                              "service": (port.find("service") or {}).get("name", "")
                              if port.find("service") is not None else ""})
        if ports:
            appareils.append({"ip": adr.get("ipv4", ""), "mac": adr.get("mac", ""), "ports": ports})
    return appareils


def build_vulnscan_tools(scan: "Callable | None" = None, reseau: str = "") -> list:
    from tools import Tool

    import config
    if not config.VULNSCAN:
        return []
    scan = scan or _scan_nmap
    cible = reseau or config.VULNSCAN_RESEAU

    def audit_reseau() -> str:
        try:
            appareils = scan(cible)
        except Exception as exc:
            return f"Je n'ai pas pu lancer l'audit réseau : {exc}"
        return rapport(evaluer_reseau(appareils))

    return [Tool(
        name="audit_reseau",
        description=("Audite la posture du réseau : appareils, ports exposés, firmwares "
                     "périmés, risques connus — SANS rien attaquer. « audit sécurité », "
                     "« mes appareils sont-ils sûrs ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=audit_reseau,
    )]
