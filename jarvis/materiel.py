"""Santé du matériel — Jarvis surveille la machine où il vit, et se protège.

Jarvis tourne sur un vrai ordinateur (souvent un mini-PC). S'il surchauffe, si le disque
se remplit, si la RAM s'épuise ou si le disque agonise (SMART), ce module le repère et
PREND des initiatives — en gardant la ligne du projet :
- INITIATIVES SÛRES, autonomes : alerter ; et surtout RÉDUIRE SA PROPRE CHARGE quand ça
  chauffe ou manque de ressources (ex. reporter le travail de nuit). C'est réversible et
  ça n'affecte que Jarvis lui-même.
- INITIATIVE DRASTIQUE (arrêt de protection sur surchauffe CRITIQUE) : opt-in, annoncée,
  avec un délai — car éteindre la machine coupe aussi la domotique. Jamais par défaut.

Lecture seule pour les mesures ; local ; sans dépendance (on lit /sys, /proc, shutil, os).
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("jarvis.materiel")

_ORDRE = {"ok": 0, "attention": 1, "critique": 2}


def _pire(a: str, b: str) -> str:
    return a if _ORDRE[a] >= _ORDRE[b] else b


# --- Lecture des mesures (best-effort : une mesure absente vaut None) -----------------

def _temp_cpu() -> "float | None":
    temps = []
    for p in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            temps.append(int(Path(p).read_text()) / 1000.0)
        except (OSError, ValueError):
            continue
    return max(temps) if temps else None


def _disque_pct(chemin: str) -> "float | None":
    try:
        u = shutil.disk_usage(chemin)
        return u.used / u.total * 100 if u.total else None
    except OSError:
        return None


def parse_meminfo(texte: str) -> "tuple[float | None, float]":
    """(RAM disponible en %, swap utilisé en %) à partir du contenu de /proc/meminfo."""
    info = {}
    for ligne in texte.splitlines():
        cle, _, reste = ligne.partition(":")
        champs = reste.split()
        if champs:
            try:
                info[cle.strip()] = float(champs[0])
            except ValueError:
                pass
    total, dispo = info.get("MemTotal"), info.get("MemAvailable")
    ram = dispo / total * 100 if total and dispo is not None else None
    swt, swf = info.get("SwapTotal", 0.0), info.get("SwapFree", 0.0)
    swap = (swt - swf) / swt * 100 if swt else 0.0
    return ram, swap


def _ram() -> "tuple[float | None, float]":
    try:
        return parse_meminfo(Path("/proc/meminfo").read_text("utf-8"))
    except OSError:
        return (None, 0.0)


def _charge() -> "float | None":
    try:
        return os.getloadavg()[0]
    except OSError:
        return None


def _smart(dev: str, run: Callable = subprocess.run) -> "str | None":
    if not dev:
        return None
    try:
        r = run(["smartctl", "-H", dev], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    sortie = (r.stdout or "").upper()
    if "FAILED" in sortie or "FAILING" in sortie:
        return "FAILED"
    if "PASSED" in sortie or "OK" in sortie:
        return "PASSED"
    return None


def lire_materiel(chemins=(), smart_dev: str = "", run: Callable = subprocess.run) -> dict:
    ram, swap = _ram()
    disques = {}
    for c in (chemins or ("/",)):
        pct = _disque_pct(c)
        if pct is not None:
            disques[c] = pct
    return {"cpu_temp": _temp_cpu(), "disques": disques, "ram_dispo": ram,
            "swap": swap, "charge": _charge(), "smart": _smart(smart_dev, run)}


# --- Évaluation (pure, testable) -----------------------------------------------------

def evaluer(m: dict, *, temp_warn=75.0, temp_crit=85.0, disque_warn=85.0, disque_crit=95.0,
            ram_warn=15.0, ram_crit=7.0) -> "tuple[str, list, bool]":
    """Renvoie (niveau, alertes[(critique, message)], sous_pression)."""
    niveau = "ok"
    alertes = []
    pression = False

    t = m.get("cpu_temp")
    if t is not None:
        if t >= temp_crit:
            alertes.append((True, f"🔥 Température CPU CRITIQUE : {t:.0f} °C")); niveau = "critique"; pression = True
        elif t >= temp_warn:
            alertes.append((False, f"🌡️ Température CPU élevée : {t:.0f} °C")); niveau = _pire(niveau, "attention"); pression = True

    for chemin, pct in (m.get("disques") or {}).items():
        if pct >= disque_crit:
            alertes.append((True, f"💽 Disque presque plein ({chemin}) : {pct:.0f} %")); niveau = "critique"; pression = True
        elif pct >= disque_warn:
            alertes.append((False, f"💽 Disque qui se remplit ({chemin}) : {pct:.0f} %")); niveau = _pire(niveau, "attention")

    ram = m.get("ram_dispo")
    if ram is not None:
        if ram <= ram_crit:
            alertes.append((True, f"🧠 Mémoire vive presque épuisée : {ram:.0f} % libre")); niveau = "critique"; pression = True
        elif ram <= ram_warn:
            alertes.append((False, f"🧠 Mémoire vive basse : {ram:.0f} % libre")); niveau = _pire(niveau, "attention"); pression = True

    if m.get("smart") == "FAILED":
        alertes.append((True, "⚠️ Le disque annonce une DÉFAILLANCE imminente (SMART). Sauvegarde d'urgence."))
        niveau = "critique"; pression = True

    return niveau, alertes, pression


# --- État de protection partagé (les tâches lourdes le consultent pour se délester) ---

class ProtectionMateriel:
    def __init__(self):
        self.niveau = "ok"
        self._pression = False

    def maj(self, niveau: str, pression: bool) -> None:
        self.niveau = niveau
        self._pression = pression

    @property
    def sous_pression(self) -> bool:
        return self._pression

    def doit_s_alleger(self) -> bool:
        """True = Jarvis devrait reporter ses tâches lourdes (il protège la machine)."""
        return self._pression


_PROTECTION = ProtectionMateriel()


def protection() -> ProtectionMateriel:
    return _PROTECTION


def sous_pression() -> bool:
    """Lu par les tâches gourmandes (ex. amélioration de nuit) pour se délester."""
    return _PROTECTION.sous_pression


def _arret_reel(delai_s: float) -> None:
    minutes = max(1, int(round(delai_s / 60)))
    subprocess.run(["shutdown", "-h", f"+{minutes}"], capture_output=True, timeout=15)


class MaterielMonitor:
    def __init__(self, lire: Callable[[], dict], seuils: dict,
                 arreter: "Callable[[float], None] | None" = None, arret_actif: bool = False,
                 arret_delai: float = 30.0, annoncer: "Callable[[str], None] | None" = None):
        self.lire = lire
        self.seuils = seuils
        self.arreter = arreter
        self.arret_actif = arret_actif
        self.arret_delai = arret_delai
        self.annoncer = annoncer
        self._vus: set = set()
        self._arret_lance = False

    def check(self) -> list:
        """Un cycle : met à jour la protection, renvoie les alertes NOUVELLES, protège si critique."""
        m = self.lire()
        niveau, alertes, pression = evaluer(m, **self.seuils)
        _PROTECTION.maj(niveau, pression)
        nouvelles = []
        for critique, message in alertes:
            if message in self._vus:
                continue
            self._vus.add(message)
            nouvelles.append((critique, message))
        if niveau == "critique" and any("Température" in msg for _, msg in alertes):
            self._proteger(m)
        return nouvelles

    def _proteger(self, m: dict) -> None:
        if not self.arret_actif or self._arret_lance or self.arreter is None:
            return
        self._arret_lance = True
        t = m.get("cpu_temp")
        if self.annoncer is not None:
            try:
                self.annoncer(f"🛑 Surchauffe critique ({t:.0f} °C). Arrêt de protection dans "
                              f"{int(self.arret_delai)} s pour éviter d'abîmer la machine "
                              f"(« shutdown -c » pour annuler).")
            except Exception:
                log.exception("annonce d'arrêt")
        try:
            self.arreter(self.arret_delai)
        except Exception:
            log.exception("arrêt de protection")

    def etat(self) -> str:
        m = self.lire()
        bouts = []
        if m.get("cpu_temp") is not None:
            bouts.append(f"CPU {m['cpu_temp']:.0f} °C")
        for c, p in (m.get("disques") or {}).items():
            bouts.append(f"disque {c} {p:.0f} %")
        if m.get("ram_dispo") is not None:
            bouts.append(f"RAM {m['ram_dispo']:.0f} % libre")
        if m.get("charge") is not None:
            bouts.append(f"charge {m['charge']:.1f}")
        if m.get("smart"):
            bouts.append(f"SMART {m['smart']}")
        _, alertes, _ = evaluer(m, **self.seuils)
        base = "🖥️ Matériel : " + (", ".join(bouts) if bouts else "aucun capteur lisible")
        if alertes:
            return base + "\n" + "\n".join("- " + msg for _, msg in alertes)
        return base + " — tout va bien."


class HardwareWatcher(threading.Thread):
    def __init__(self, monitor: MaterielMonitor, notify: Callable[[str], None], interval_s: float = 60.0):
        super().__init__(daemon=True, name="jarvis-materiel")
        self.monitor = monitor
        self.notify = notify
        self.interval_s = interval_s
        self._halt = threading.Event()

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            try:
                for critique, message in self.monitor.check():
                    prefixe = "🚨 MATÉRIEL" if critique else "🖥️"
                    self.notify(f"{prefixe} {message}")
            except Exception:
                log.exception("surveillance matérielle")

    def arreter(self) -> None:
        self._halt.set()


def _seuils() -> dict:
    import config
    return {"temp_warn": config.MAT_TEMP_WARN, "temp_crit": config.MAT_TEMP_CRIT,
            "disque_warn": config.MAT_DISQUE_WARN, "disque_crit": config.MAT_DISQUE_CRIT,
            "ram_warn": config.MAT_RAM_WARN, "ram_crit": config.MAT_RAM_CRIT}


_MON: "MaterielMonitor | None" = None


def _moniteur() -> MaterielMonitor:
    global _MON
    if _MON is None:
        import config
        lire = lambda: lire_materiel(config.MAT_DISQUE_CHEMINS, config.MAT_SMART_DEV)  # noqa: E731
        _MON = MaterielMonitor(lire, _seuils(),
                               arreter=_arret_reel if config.MAT_ARRET else None,
                               arret_actif=config.MAT_ARRET, arret_delai=config.MAT_ARRET_DELAI)
    return _MON


def make_materiel_watcher(notify: Callable[[str], None]) -> "HardwareWatcher | None":
    import config
    if not config.MATERIEL:
        return None
    mon = _moniteur()
    mon.annoncer = notify     # pour annoncer un éventuel arrêt de protection
    return HardwareWatcher(mon, notify, interval_s=config.MATERIEL_INTERVALLE)


def build_materiel_tools() -> list:
    import config
    from tools import Tool

    if not config.MATERIEL:
        return []
    mon = _moniteur()
    return [Tool(
        name="etat_materiel",
        description=("Donne l'état de SANTÉ de la machine : température CPU, remplissage des "
                     "disques, mémoire vive, charge, SMART. « comment va la machine ? », "
                     "« est-ce que ça chauffe ? », « le disque est plein ? »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=lambda: mon.etat(),
    )]
