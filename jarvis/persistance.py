"""Détection de persistance — repérer la porte dérobée qu'un intrus laisse APRÈS coup.

La sentinelle (sentinel) voit les nouveaux ports, les appareils, le pare-feu. Elle ne
voit PAS le grand classique de l'après-intrusion : l'attaquant qui s'installe pour
revenir — une clé SSH ajoutée à authorized_keys, une tâche cron, un service d'autostart,
un `.bashrc` piégé. Ce module surveille précisément ces mécanismes de persistance.

Ligne tenue (cohérente avec le reste du projet) :
- LECTURE SEULE + ALERTE. On NE supprime JAMAIS tout seul une clé/cron/fichier : ça
  casserait un accès légitime et détruirait une preuve. Jarvis DÉTECTE, tu décides.
- Première exécution = on fait CONFIANCE à l'état courant (référence silencieuse). Ensuite,
  tout AJOUT est signalé jusqu'à ce que tu l'acceptes (« accepte la persistance »).

Se branche dans SecurityWatcher comme les autres checkers : .check() -> [(critique, msg)].
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Callable, Iterator

log = logging.getLogger("jarvis.persistance")

# Fichiers de démarrage de shell (un intrus y glisse une commande qui se relance à chaque login).
_RC = (".bashrc", ".zshrc", ".profile", ".bash_profile", ".bash_login", ".bash_logout", ".ssh/config")
# authorized_keys : une clé ajoutée ici = accès SSH permanent sans mot de passe.
_AUTHORIZED = (".ssh/authorized_keys", ".ssh/authorized_keys2")
# Dossiers de démarrage automatique (un service/un .desktop ajouté = relance au boot/login).
_AUTOSTART = (".config/autostart", ".config/systemd/user")
_PREFIXES_CLE = ("ssh-", "ecdsa-", "sk-ssh-", "sk-ecdsa-")


def _hash(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def _parse_cles(texte: str) -> list:
    """Extrait les clés d'un authorized_keys : empreinte du matériel de clé + commentaire."""
    cles = []
    for ligne in texte.splitlines():
        l = ligne.strip()
        if not l or l.startswith("#"):
            continue
        parts = l.split()
        idx = next((i for i, p in enumerate(parts) if p.startswith(_PREFIXES_CLE)), None)
        if idx is not None and idx + 1 < len(parts):
            blob = parts[idx + 1]
            comment = " ".join(parts[idx + 2:])
        else:                                   # format inattendu : on empreinte la ligne entière
            blob, comment = l, ""
        cles.append({"empreinte": hashlib.sha256(blob.encode()).hexdigest()[:16],
                     "comment": comment})
    return cles


def _crontab_reel() -> str:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _lignes_cron(texte: str) -> list:
    return [l.strip() for l in (texte or "").splitlines()
            if l.strip() and not l.strip().startswith("#")]


class Collecteur:
    """Prend une photo de la surface de persistance. home/run_cron injectables (tests)."""

    def __init__(self, home: "Path | None" = None, run_cron: Callable[[], str] = _crontab_reel):
        self.home = Path(home) if home is not None else Path.home()
        self.run_cron = run_cron

    def instantane(self) -> dict:
        cles = {}
        for rel in _AUTHORIZED:
            p = self.home / rel
            if p.is_file():
                try:
                    cles[str(p)] = _parse_cles(p.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    log.debug("lecture %s", p, exc_info=True)
        fichiers = {}
        for rel in _RC:
            p = self.home / rel
            if p.is_file():
                fichiers[str(p)] = _hash(p)
        for rel in _AUTOSTART:
            d = self.home / rel
            if d.is_dir():
                for p in sorted(d.rglob("*")):
                    if p.is_file():
                        fichiers[str(p)] = _hash(p)
        return {"cles_ssh": cles, "cron": _lignes_cron(self.run_cron()), "fichiers": fichiers}


def _est_autostart(chemin: str) -> bool:
    return "/autostart" in chemin or "/systemd/" in chemin


def comparer(base: dict, actuel: dict) -> "Iterator[tuple[bool, str]]":
    """Diffs entre deux photos. (critique, message). Clé SSH / cron ajoutés = critiques."""
    # --- Clés SSH ---
    for chemin in sorted(set(base.get("cles_ssh", {})) | set(actuel.get("cles_ssh", {}))):
        avant = {c["empreinte"]: c for c in base.get("cles_ssh", {}).get(chemin, [])}
        apres = {c["empreinte"]: c for c in actuel.get("cles_ssh", {}).get(chemin, [])}
        for fp in sorted(apres.keys() - avant.keys()):
            com = apres[fp].get("comment") or "(sans commentaire)"
            yield True, f"🔑 Nouvelle clé SSH autorisée dans {chemin} — « {com} » (porte dérobée possible)"
        for fp in sorted(avant.keys() - apres.keys()):
            com = avant[fp].get("comment") or "(sans commentaire)"
            yield False, f"Clé SSH retirée de {chemin} — « {com} »"
    # --- Cron ---
    avant_cron, apres_cron = set(base.get("cron", [])), set(actuel.get("cron", []))
    for ligne in sorted(apres_cron - avant_cron):
        yield True, f"⏰ Nouvelle tâche planifiée (cron) : {ligne}"
    for ligne in sorted(avant_cron - apres_cron):
        yield False, f"Tâche cron retirée : {ligne}"
    # --- Fichiers de démarrage / autostart ---
    avant_f, apres_f = base.get("fichiers", {}), actuel.get("fichiers", {})
    for chemin in sorted(apres_f.keys() - avant_f.keys()):
        quoi = "démarrage automatique" if _est_autostart(chemin) else "fichier de démarrage"
        yield False, f"🆕 Nouveau {quoi} : {chemin}"
    for chemin in sorted(avant_f.keys() - apres_f.keys()):
        yield False, f"Fichier de démarrage supprimé : {chemin}"
    for chemin in sorted(apres_f.keys() & avant_f.keys()):
        if apres_f[chemin] != avant_f[chemin]:
            yield False, f"📝 Fichier de démarrage modifié : {chemin}"


class PersistenceMonitor:
    def __init__(self, collecteur: Collecteur, store):
        self.collecteur = collecteur
        self.store = store

    def check(self) -> list:
        """Checker pour SecurityWatcher : alertes NOUVELLES depuis la référence."""
        actuel = self.collecteur.instantane()
        base = self.store.data.get("base")
        if base is None:                         # 1re fois : l'état courant devient la référence
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
            return "Référence de persistance établie (clés SSH, cron, démarrage). RAS pour l'instant."
        lignes = [m for _, m in comparer(base, actuel)]
        if not lignes:
            return "Persistance : RAS — aucune clé SSH, tâche cron ou fichier de démarrage inattendu."
        return "⚠️ Changements sur la surface de persistance :\n" + "\n".join(f"- {m}" for m in lignes)

    def accepter(self) -> str:
        """Le propriétaire a revu les changements : ils deviennent la nouvelle référence."""
        self.store.data["base"] = self.collecteur.instantane()
        self.store.save()
        return "✅ État de persistance actuel accepté comme nouvelle référence."


_MONITOR: "PersistenceMonitor | None" = None


def _monitor() -> PersistenceMonitor:
    global _MONITOR
    if _MONITOR is None:
        import config
        from skills import JsonStore
        _MONITOR = PersistenceMonitor(Collecteur(), JsonStore(config.PERSISTENCE_FILE, {}))
    return _MONITOR


def make_persistence_monitor() -> "PersistenceMonitor | None":
    import config
    return _monitor() if getattr(config, "PERSISTENCE", False) else None


def build_persistence_tools() -> list:
    import config
    from tools import Tool

    if not getattr(config, "PERSISTENCE", False):
        return []
    mon = _monitor()
    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="verifier_persistance",
             description=("Vérifie les mécanismes de PERSISTANCE (portes dérobées) : clé SSH ajoutée à "
                          "authorized_keys, tâche cron, service d'autostart, fichier de démarrage modifié. "
                          "« y a-t-il une porte dérobée ? », « vérifie la persistance »."),
             parameters=vide, run=lambda: mon.rapport()),
        Tool(name="accepter_persistance",
             description=("Accepte l'état de persistance ACTUEL comme nouvelle référence (après avoir "
                          "revu les changements). À utiliser quand TU as ajouté une clé/cron légitime."),
             parameters=vide, run=lambda: mon.accepter(),
             confirm=lambda: ("Je vais prendre l'état actuel (clés SSH, cron, démarrage) comme référence : "
                              "les alertes en cours seront effacées. Tu confirmes ?")),
    ]
