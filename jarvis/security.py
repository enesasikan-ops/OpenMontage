"""La sentinelle : Jarvis surveille les signes d'intrusion sur le PC et prévient.

Il ne remplace ni l'antivirus ni le pare-feu : il les surveille, et il remarque
ce qui CHANGE sur la machine par rapport à un état de référence mémorisé :
- un nouveau programme qui accepte des connexions venant du réseau ;
- un nouveau programme lancé au démarrage (Windows) ;
- un nouveau compte administrateur (Windows) ;
- un nouvel appareil vu sur le réseau local ;
- le pare-feu désactivé, une menace détectée par Windows Defender (Windows).

Tout est en lecture seule et reste sur l'ordinateur. Seule action possible, à la
demande et après confirmation : lancer une analyse antivirus.
"""

import json
import platform
import re
import subprocess
from pathlib import Path
from typing import Callable

from skills import JsonStore

Run = Callable[..., subprocess.CompletedProcess]

DYNAMIC_PORT = 49152
LOCAL_ONLY = ("127.", "::1", "localhost")
MAC_RE = re.compile(r"\b([0-9a-f]{2}(?:[:-][0-9a-f]{2}){5})\b", re.IGNORECASE)
IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")

CATEGORY_TEXT = {
    "ports": "un nouveau programme accepte des connexions venant du réseau : {}",
    "demarrage": "un nouveau programme se lance au démarrage : {}",
    "admins": "un nouveau compte administrateur est apparu : {}",
    "appareils": "un appareil inconnu est apparu sur le réseau : {}",
    "menaces": "Windows Defender a détecté une menace : {}",
}
CRITICAL = {"admins", "menaces"}


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _powershell(command: str, run: Run) -> list[dict]:
    """Exécute une commande PowerShell de lecture et renvoie une liste d'objets."""
    out = run(["powershell", "-NoProfile", "-Command", f"{command} | ConvertTo-Json -Compress"],
              capture_output=True, text=True, timeout=30)
    text = (out.stdout or "").strip()
    if not text:
        return []
    data = json.loads(text)
    items = data if isinstance(data, list) else [data]
    return [i if isinstance(i, dict) else {"value": i} for i in items]


# --- Ce qu'on observe ------------------------------------------------------------------


def listening_programs() -> dict[str, str]:
    """Programmes qui acceptent des connexions depuis le réseau (pas seulement en local)."""
    import psutil

    found = {}
    try:
        connections = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        return {}
    for c in connections:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        if str(c.laddr.ip).startswith(LOCAL_ONLY):
            continue
        try:
            name = psutil.Process(c.pid).name() if c.pid else "inconnu"
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = "inconnu"
        port = c.laddr.port
        if port >= DYNAMIC_PORT:  # ports temporaires : on suit le programme, pas le numéro
            found[f"{name}:dynamique"] = f"{name} (port temporaire)"
        else:
            found[f"{name}:{port}"] = f"{name} (port {port})"
    return found


def network_devices(run: Run = subprocess.run) -> dict[str, str]:
    """Appareils du réseau local que l'ordinateur a déjà croisés (table ARP)."""
    try:
        out = run(["arp", "-a"], capture_output=True, text=True, timeout=15).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return {}
    found = {}
    for line in out.splitlines():
        mac, ip = MAC_RE.search(line), IP_RE.search(line)
        if not mac or not ip:
            continue
        m = mac.group(1).lower().replace("-", ":")
        if m.startswith(("ff:ff", "01:00:5e", "33:33", "00:00:00")):  # diffusion, pas un appareil
            continue
        found[m] = f"adresse {ip.group(1)} (identifiant {m})"
    return found


def startup_programs(run: Run = subprocess.run) -> dict[str, str]:
    if not _is_windows():
        return {}
    items = _powershell("Get-CimInstance Win32_StartupCommand | Select-Object Name,Command", run)
    return {f"{i.get('Name')}|{i.get('Command')}": str(i.get("Name")) for i in items}


def admin_accounts(run: Run = subprocess.run) -> dict[str, str]:
    if not _is_windows():
        return {}
    # S-1-5-32-544 = groupe Administrateurs, quel que soit la langue de Windows.
    items = _powershell("Get-LocalGroupMember -SID S-1-5-32-544 | Select-Object Name", run)
    return {str(i.get("Name")): str(i.get("Name")) for i in items}


def defender_threats(run: Run = subprocess.run) -> dict[str, str]:
    if not _is_windows():
        return {}
    items = _powershell("Get-MpThreat | Select-Object ThreatID,ThreatName", run)
    return {str(i.get("ThreatID")): str(i.get("ThreatName")) for i in items}


def firewall_off(run: Run = subprocess.run) -> list[str]:
    """Profils du pare-feu Windows désactivés."""
    if not _is_windows():
        return []
    items = _powershell("Get-NetFirewallProfile | Select-Object Name,Enabled", run)
    return [str(i.get("Name")) for i in items if i.get("Enabled") in (False, 0)]


def snapshot(run: Run = subprocess.run) -> dict[str, dict[str, str]]:
    sources = {
        "ports": listening_programs,
        "appareils": lambda: network_devices(run),
        "demarrage": lambda: startup_programs(run),
        "admins": lambda: admin_accounts(run),
        "menaces": lambda: defender_threats(run),
    }
    result = {}
    for name, source in sources.items():
        try:
            result[name] = source()
        except Exception:  # une source illisible ne doit pas masquer les autres
            result[name] = {}
    return result


# --- La sentinelle -------------------------------------------------------------------------


class Sentinel:
    def __init__(self, path: Path, take_snapshot: Callable[[], dict] = snapshot,
                 firewall: Callable[[], list[str]] = firewall_off):
        self.path = path
        self.take_snapshot = take_snapshot
        self.firewall = firewall
        self._firewall_alerted = False

    def _load(self) -> JsonStore:
        return JsonStore(self.path, {})

    def check(self) -> list[tuple[bool, str]]:
        """Compare la machine à l'état de référence. Renvoie [(critique ?, message)].

        Chaque nouveauté est signalée une seule fois, puis ajoutée à la référence.
        """
        store = self._load()
        current = self.take_snapshot()
        events: list[tuple[bool, str]] = []

        if not store.data:  # premier passage : on mémorise, on n'alerte pas
            store.data = {k: sorted(v) for k, v in current.items()}
            store.save()
            total = sum(len(v) for v in current.values())
            events.append((False, f"la sentinelle est en place : j'ai mémorisé l'état actuel de "
                                  f"la machine ({total} éléments). Je vous préviendrai de tout changement"))
        else:
            changed = False
            for category, items in current.items():
                known = set(store.data.get(category, []))
                for key, label in items.items():
                    if key not in known:
                        events.append((category in CRITICAL, CATEGORY_TEXT[category].format(label)))
                        known.add(key)
                        changed = True
                store.data[category] = sorted(known)
            if changed:
                store.save()

        try:
            off = self.firewall()
        except Exception:
            off = []
        if off and not self._firewall_alerted:
            events.append((True, "le pare-feu Windows est désactivé (" + ", ".join(off) + ")"))
        self._firewall_alerted = bool(off)
        return events

    def report(self) -> str:
        """Résumé pour « Jarvis, rapport de sécurité ». Ne modifie pas la référence."""
        current = self.take_snapshot()
        parts = []
        ports = current.get("ports", {})
        if ports:
            parts.append(f"{len(ports)} programme(s) acceptent des connexions du réseau : "
                         + ", ".join(sorted(ports.values())))
        else:
            parts.append("Aucun programme n'accepte de connexion venant du réseau")
        parts.append(f"{len(current.get('appareils', {}))} appareil(s) vus sur le réseau local")
        if _is_windows():
            try:
                off = self.firewall()
            except Exception:
                off = []
            parts.append("ATTENTION, pare-feu désactivé" if off else "Pare-feu actif")
            threats = current.get("menaces", {})
            parts.append(f"ATTENTION, {len(threats)} menace(s) dans l'historique de Defender : "
                         + ", ".join(threats.values()) if threats else "Aucune menace détectée par Defender")
            parts.append(f"{len(current.get('admins', {}))} compte(s) administrateur")
            parts.append(f"{len(current.get('demarrage', {}))} programme(s) au démarrage")
        else:
            parts.append("Pare-feu, antivirus et comptes : vérifiés uniquement sous Windows")
        return ". ".join(parts) + "."


def start_antivirus_scan(run: Run = subprocess.run) -> str:
    """Lance une analyse rapide de Windows Defender (en arrière-plan)."""
    if not _is_windows():
        return "L'analyse antivirus n'est disponible que sous Windows."
    try:
        run(["powershell", "-NoProfile", "-Command", "Start-MpScan -ScanType QuickScan -AsJob | Out-Null"],
            capture_output=True, text=True, timeout=30, check=True)
    except Exception:
        return "Je n'ai pas réussi à lancer l'analyse antivirus."
    return ("Analyse antivirus rapide lancée. Elle prend quelques minutes ; "
            "si elle trouve une menace, je vous préviendrai.")
