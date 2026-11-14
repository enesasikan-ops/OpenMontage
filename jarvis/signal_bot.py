"""Bot Signal deux-sens : parler à Jarvis par Signal (chiffré bout en bout).

Équivalent de telegram_bot.py, mais Signal n'a pas de boutons : l'approbation se fait
par réponse texte.
  - Action sensible      -> Jarvis demande « OUI ou NON », tu réponds oui / non.
  - Amélioration de nuit -> Jarvis envoie la proposition, tu réponds « valide 3 » /
                            « rejette 3 » (ou juste oui / non pour la dernière).

Sécurité : le bot ne répond qu'à TON numéro (JARVIS_SIGNAL_DESTINATAIRE).

Le cœur (SignalJarvis) est indépendant du transport : il reçoit (expéditeur, texte) et
envoie via une fonction `envoyer`. Le transport réel (signal-cli) est branché dans main().
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


def _ecrire_diff(fichier: str, diff: str) -> str:
    """Écrit le diff dans un fichier temporaire (pour l'envoyer en pièce jointe) et renvoie son chemin."""
    nom = fichier.replace("/", "_").replace(".", "_")
    chemin = Path(tempfile.gettempdir()) / f"jarvis_coeur_{nom}.diff"
    chemin.write_text(diff or "(aucun changement)", encoding="utf-8")
    return str(chemin)

CONFIRM_TIMEOUT_S = 180

_OUI = re.compile(r"^\s*(oui|o|ok|yes|y|valide|active|d'accord|vas-y)\b", re.IGNORECASE)
_NON = re.compile(r"^\s*(non|n|no|rejette|refuse|annule|stop)\b", re.IGNORECASE)
_PROPOSITION = re.compile(
    r"^\s*(?P<verbe>valide|active|accepte|rejette|refuse|oui|non)\s*(?P<id>\d+)?\s*$",
    re.IGNORECASE)
_VERBES_POUR = {"valide", "active", "accepte", "oui"}


class SignalJarvis:
    """Logique du bot, sans transport. `envoyer(texte, piece_jointe=None)`."""

    def __init__(self, brain_factory, owner_number: str, envoyer: Callable):
        self.owner = (owner_number or "").strip()
        self.envoyer = envoyer
        self._lock = threading.Lock()          # une conversation à la fois
        self._attente: "tuple[threading.Event, list[bool]] | None" = None
        self._derniere_proposition: int | None = None
        self.proposals = None                  # renseigné au démarrage (nuit)
        self.core = None                       # CoreImprover (changements du cœur), facultatif
        self._core_pending = None              # proposition de cœur en attente de ta validation
        self.integrity = None                  # tripwire d'intégrité du cœur, facultatif
        self.backup = None                     # CoreBackup : restaurer le cœur si trafiqué
        self.blocker = None                    # IpBlocker : bloquer une IP au pare-feu (défensif)
        self.brain = brain_factory(self._confirmer, self._statut)

    # --- Sorties vers toi --------------------------------------------------------

    def _statut(self, texte: str) -> None:
        self.envoyer(f"⏳ {texte}")

    def notify_owner(self, texte: str) -> None:
        self.envoyer(texte)

    def send_proposal(self, texte: str, pid: int) -> None:
        """Annonce une amélioration codée cette nuit (réponse texte : valide / rejette)."""
        self._derniere_proposition = pid
        self.envoyer(f"{texte}\n\nPour l'activer réponds : valide {pid} — pour refuser : rejette {pid}.")

    # --- Confirmation d'une action sensible (appelée depuis le thread du cerveau) -

    def _confirmer(self, description: str) -> bool:
        event, answer = threading.Event(), [False]
        self._attente = (event, answer)
        self.envoyer(f"⚠️ {description}\nRéponds OUI ou NON.")
        if not event.wait(CONFIRM_TIMEOUT_S):
            self.envoyer("⌛ Pas de réponse, j'annule.")
        self._attente = None
        return answer[0]

    # --- Entrée : un message reçu ------------------------------------------------

    def traiter(self, expediteur: str, texte: str) -> None:
        """Route un message reçu. Ignore tout numéro autre que le propriétaire."""
        if self.owner and expediteur.strip() != self.owner:
            log.warning("Message ignoré d'un numéro non autorisé : %s", expediteur)
            return
        texte = (texte or "").strip()
        if not texte:
            return

        # 1. Une confirmation est en attente -> ce message est la réponse oui/non.
        if self._attente is not None:
            event, answer = self._attente
            answer[0] = bool(_OUI.match(texte)) and not _NON.match(texte)
            event.set()
            return

        # 2. Changement du cœur : « cœur drone.py: augmente la limite » (réservé à toi).
        coeur = re.match(r"^\s*c(?:œ|oe)ur\s+(?P<fichier>\S+)\s*:\s*(?P<consigne>.+)$", texte, re.IGNORECASE)
        if coeur:
            self._proposer_coeur(coeur.group("fichier"), coeur.group("consigne"))
            return
        if re.match(r"^\s*(valide|active|accepte)\s+c(?:œ|oe)ur\b", texte, re.IGNORECASE):
            self._appliquer_coeur(True)
            return
        if re.match(r"^\s*(rejette|refuse|annule)\s+c(?:œ|oe)ur\b", texte, re.IGNORECASE):
            self._appliquer_coeur(False)
            return
        # Accepter un changement du cœur fait hors du bot (ex. une mise à jour que tu as relue).
        if re.match(r"^\s*(rebase|rebaser|accepte|base)\s+c(?:œ|oe)ur\b", texte, re.IGNORECASE):
            if self.integrity is not None:
                self.envoyer("🛡️ " + self.integrity.rebaser())
            else:
                self.envoyer("La surveillance d'intégrité n'est pas active.")
            return
        # Défense active : sauvegarder l'état sain du cœur, ou restaurer un fichier trafiqué.
        if re.match(r"^\s*sauvegarde\s+c(?:œ|oe)ur\b", texte, re.IGNORECASE):
            self._sauvegarder_coeur()
            return
        restaure = re.match(r"^\s*restaure[r]?\s+c(?:œ|oe)ur\s+(?P<fichier>\S+)", texte, re.IGNORECASE)
        if restaure:
            self._restaurer_coeur(restaure.group("fichier"))
            return
        # Blocage d'IP défensif (sur ta décision, après une alerte).
        bloc = re.match(r"^\s*bloque[r]?\s+(?P<ip>\S+)", texte, re.IGNORECASE)
        if bloc:
            self._bloquer_ip(bloc.group("ip"), True)
            return
        debloc = re.match(r"^\s*d[ée]bloque[r]?\s+(?P<ip>\S+)", texte, re.IGNORECASE)
        if debloc:
            self._bloquer_ip(debloc.group("ip"), False)
            return
        if re.match(r"^\s*(blocages|liste des blocages|ip bloqu)", texte, re.IGNORECASE):
            if self.blocker is None:
                self.envoyer("Le blocage d'IP n'est pas actif.")
            else:
                ips = self.blocker.liste()
                self.envoyer("IP bloquées : " + (", ".join(ips) if ips else "aucune."))
            return

        # 3. Décision sur une proposition d'amélioration (valide 3 / rejette 3 / oui / non).
        decision = self._decision_proposition(texte)
        if decision is not None:
            self._traiter_proposition(*decision)
            return

        # 4. Sinon : une question normale pour le cerveau.
        self._repondre(texte)

    # --- Changements du cœur (Gemini propose, tu lis le diff, tu valides) ---------

    def _proposer_coeur(self, fichier: str, consigne: str) -> None:
        if self.core is None:
            self.envoyer("Le mode « cœur » n'est pas activé.")
            return

        def travail():
            try:
                self.envoyer(f"⏳ Gemini prépare une proposition pour {fichier}…")
                prop = self.core.proposer(fichier, consigne)
            except Exception as exc:
                self.envoyer(f"Impossible : {exc}")
                return
            self._core_pending = prop
            etat = "✅ tests OK" if prop.tests_ok else f"⚠️ TESTS EN ÉCHEC ({prop.tests})"
            piece = _ecrire_diff(prop.fichier, prop.diff)
            self.envoyer(
                f"Proposition pour le CŒUR — {prop.fichier}\n{etat}\n\n"
                "Lis le diff (en pièce jointe) AVANT de décider.\n"
                "Réponds : valide cœur — ou — rejette cœur.",
                piece_jointe=piece)

        threading.Thread(target=travail, name="jarvis-coeur", daemon=True).start()

    def _appliquer_coeur(self, accepter: bool) -> None:
        prop = self._core_pending
        if prop is None:
            self.envoyer("Aucune proposition de cœur en attente.")
            return
        self._core_pending = None
        if not accepter:
            self.envoyer("Proposition de cœur rejetée. Rien changé.")
            return
        if not prop.tests_ok:
            self.envoyer("Je n'applique pas : les tests de cette proposition échouent. "
                         "Redemande une proposition corrigée.")
            return
        try:
            message = self.core.appliquer(prop)
            if self.integrity is not None:
                self.integrity.rebaser()   # ce changement est validé : on accepte la nouvelle empreinte
            if self.backup is not None:
                self.backup.sauvegarder()  # le nouvel état validé devient la référence saine
            self.envoyer(message)
        except Exception as exc:
            self.envoyer(f"Application impossible : {exc}")

    def _bloquer_ip(self, ip: str, bloquer: bool) -> None:
        if self.blocker is None:
            self.envoyer("Le blocage d'IP n'est pas actif.")
            return
        try:
            message = self.blocker.bloquer(ip) if bloquer else self.blocker.debloquer(ip)
        except Exception as exc:
            self.envoyer(f"Impossible : {exc}")
            return
        self.envoyer(message)

    def _sauvegarder_coeur(self) -> None:
        if self.backup is None:
            self.envoyer("La défense du cœur n'est pas active.")
            return
        n = self.backup.sauvegarder()
        self.envoyer(f"🛡️ État sain du cœur sauvegardé ({n} fichiers). "
                     "Je pourrai restaurer si on les trafique.")

    def _restaurer_coeur(self, fichier: str) -> None:
        if self.backup is None:
            self.envoyer("La défense du cœur n'est pas active.")
            return
        try:
            message = self.backup.restaurer(fichier)
        except Exception as exc:
            self.envoyer(f"Restauration impossible : {exc}")
            return
        if self.integrity is not None:
            self.integrity.rebaser()   # le fichier est revenu à l'état sain : on réaligne la référence
        self.envoyer("🛡️ " + message)

    def _decision_proposition(self, texte: str) -> "tuple[bool, int] | None":
        m = _PROPOSITION.match(texte)
        if m is None:
            return None
        pid = int(m.group("id")) if m.group("id") else self._derniere_proposition
        if pid is None:
            return None
        return (m.group("verbe").lower() in _VERBES_POUR, pid)

    def _traiter_proposition(self, accepter: bool, pid: int) -> None:
        if self.proposals is None:
            self.envoyer("Aucune amélioration à valider pour le moment.")
            return
        key = str(pid)
        if accepter:
            resultat = self.proposals.activate(key)
        else:
            resultat = self.proposals.reject(key)
        self._derniere_proposition = None
        self.envoyer(resultat or ("Activée." if accepter else "Rejetée."))

    def _repondre(self, texte: str) -> None:
        """Lance le cerveau dans un thread : _confirmer peut ainsi bloquer sans figer la réception."""
        def travail():
            with self._lock:
                try:
                    reponse = self.brain.reply(texte) or "…"
                except Exception as exc:  # un plantage du cerveau ne doit pas tuer le bot
                    log.exception("Cerveau en erreur")
                    reponse = f"Désolé, j'ai eu un souci : {exc}"
            self.envoyer(reponse)

        threading.Thread(target=travail, name="jarvis-signal-reply", daemon=True).start()


# --- Transport réel : signal-cli en mode démon JSON-RPC ----------------------------
# Un seul processus signal-cli gère l'envoi ET la réception (le compte est verrouillé,
# on ne lance pas deux processus en parallèle). À vérifier une fois sur ta machine.

class SignalCliDaemon:
    """Reçoit et envoie via `signal-cli -a <compte> jsonRpc` (stdin/stdout)."""

    def __init__(self, account: str, recipient: str, signal_cli: str = "signal-cli"):
        self.account = account
        self.recipient = recipient
        self.signal_cli = signal_cli
        self.proc: "subprocess.Popen | None" = None
        self.on_message: "Callable[[str, str], None] | None" = None
        self._id = 0
        self._lock = threading.Lock()

    def demarrer(self) -> None:
        self.proc = subprocess.Popen(
            [self.signal_cli, "-a", self.account, "jsonRpc"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)
        threading.Thread(target=self._lire, name="signal-receive", daemon=True).start()

    def _lire(self) -> None:
        for ligne in self.proc.stdout:  # type: ignore[union-attr]
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                msg = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if msg.get("method") != "receive":
                continue
            env = (msg.get("params") or {}).get("envelope") or {}
            data = env.get("dataMessage") or {}
            texte = data.get("message")
            source = env.get("sourceNumber") or env.get("source")
            if texte and source and self.on_message is not None:
                try:
                    self.on_message(source, texte)
                except Exception:
                    log.exception("Erreur en traitant un message Signal")

    def envoyer(self, texte: str, piece_jointe: str | None = None) -> None:
        if self.proc is None or self.proc.stdin is None:
            log.warning("Signal pas démarré, message non envoyé.")
            return
        params = {"recipient": [self.recipient], "message": texte}
        if piece_jointe:
            params["attachments"] = [piece_jointe]
        with self._lock:
            self._id += 1
            requete = {"jsonrpc": "2.0", "method": "send", "params": params, "id": str(self._id)}
            try:
                self.proc.stdin.write(json.dumps(requete) + "\n")
                self.proc.stdin.flush()
            except OSError as exc:
                log.error("Envoi Signal échoué : %s", exc)


def main() -> None:
    import os

    import config
    from brain import Brain
    from claude_bridge import ClaudeBridge
    from main import check_ollama  # charge aussi le .env
    from memory import Memory
    from proactive import Proactive
    from security import Sentinel
    from skills import Lists, ReminderWatcher, Reminders
    from smarthome import SmartHome
    from tools import build_tools
    # Constructeurs partagés (drone, caméras, visages, Gemini) : réutilisés tels quels.
    from telegram_bot import gemini_advisor, make_cameras, make_drone, make_faces

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if config.OFFLINE:
        raise SystemExit("❌ Signal passe par internet : désactive JARVIS_HORS_LIGNE.")
    account = config._env("JARVIS_SIGNAL_EXPEDITEUR", "").strip()
    owner = config._env("JARVIS_SIGNAL_DESTINATAIRE", "").strip()
    if not account or not owner:
        raise SystemExit("❌ Renseigne JARVIS_SIGNAL_EXPEDITEUR et JARVIS_SIGNAL_DESTINATAIRE (voir signal_notify.py).")

    client = check_ollama(wait_s=180)
    memory = Memory(config.MEMORY_FILE)
    claude = ClaudeBridge()
    reminders, lists = Reminders(config.REMINDERS_FILE), Lists(config.LISTS_FILE)
    sentinel = Sentinel(config.SENTINEL_FILE) if config.SENTINEL else None
    home = SmartHome()
    gemini = gemini_advisor()
    drone = make_drone(gemini)
    faces, face_frame = make_faces(drone)
    cameras = make_cameras(gemini)
    from growth import GrowthJournal, NightlyImprover, Proposals
    growth = GrowthJournal(config.GROWTH_FILE)
    proposals = Proposals(growth)

    plugins = None
    if config.PLUGINS_HOT:
        from plugin_manager import PluginManager, build_plugin_tools
        plugins = PluginManager(interval_s=config.PLUGINS_INTERVAL)

    # Mode Sentinelle : une seule instance, partagée entre les outils et le hook de détection.
    from skills import JsonStore
    from watchdog import Watchdog
    _etat = {}
    watchdog = Watchdog(home, lambda m: _etat["jarvis"].notify_owner(m),
                        JsonStore(config.SURV_FILE, {}), config.surv_settings())

    def brain_factory(confirm, on_status):
        tools = build_tools(memory, claude, on_status=on_status, reminders=reminders, lists=lists,
                            sentinel=sentinel, home=home,
                            agent=claude if config.AGENT else None, gemini=gemini, drone=drone,
                            faces=faces, face_frame=face_frame, cameras=cameras, growth=growth,
                            proposals=proposals, plugins=plugins is None, watchdog=watchdog)
        if plugins is not None:
            tools.update({t.name: t for t in build_plugin_tools(plugins)})
        return Brain(client, tools, memory, confirm)

    transport = SignalCliDaemon(account, owner, config._env("JARVIS_SIGNAL_CLI", "signal-cli"))
    jarvis = SignalJarvis(brain_factory, owner, transport.envoyer)
    _etat["jarvis"] = jarvis          # le Watchdog peut maintenant alerter
    transport.on_message = jarvis.traiter
    transport.demarrer()

    jarvis.proposals = proposals

    # Mode « cœur » : sur TA demande explicite, Gemini propose un changement d'un fichier
    # du cœur ; tu lis le diff et tu valides. Jamais automatique, jamais sans ton accord.
    from claude_bridge import GeminiBackend, GeminiCliBackend
    from core_proposals import CoreImprover
    if config.GEMINI_KEY:
        core_agent = GeminiBackend()
    elif config.GEMINI_CLI_ENABLE:
        core_agent = GeminiCliBackend()
    else:
        core_agent = claude
    jarvis.core = CoreImprover(core_agent)

    ReminderWatcher(reminders, notify=jarvis.notify_owner).start()
    Proactive(reminders, lists, security=sentinel.check if sentinel else None,
              notify=jarvis.notify_owner).start()

    # Cybersurveillance continue + défense active : la machine ET le code de Jarvis lui-même.
    if config.CYBERWATCH:
        from core_integrity import CoreIntegrity
        from cyberwatch import SecurityWatcher
        from defense import CoreBackup, EvidenceLog
        jarvis.integrity = CoreIntegrity(config.DATA_DIR / "integrite_coeur.json")
        jarvis.backup = CoreBackup(config.DATA_DIR / "sauvegarde_coeur")
        jarvis.backup.sauvegarder()            # instantané sain au démarrage
        evidence = EvidenceLog(config.DATA_DIR / "preuves_securite.json")
        from crowdsec import make_crowdsec
        SecurityWatcher(jarvis.notify_owner, sentinel=sentinel, integrity=jarvis.integrity,
                        interval_s=config.CYBERWATCH_INTERVAL, evidence=evidence,
                        backup=jarvis.backup, auto_restore=config.AUTO_RESTORE,
                        crowdsec=make_crowdsec()).start()
        from ipblock import IpBlocker
        jarvis.blocker = IpBlocker(config.DATA_DIR / "ip_bloquees.json",
                                   liste_blanche=config.IP_LISTE_BLANCHE)
        if config.HONEYPOT:   # faux serveur leurre (aucun accès au cœur : juste preuve + alerte)
            from honeypot import Honeypot

            def _sur_intrusion(ip, user, pw):
                evidence.consigner(f"honeypot : intrusion depuis {ip} (user={user!r} pass={pw!r})")
                jarvis.notify_owner(
                    f"🍯 ALERTE : tentative d'accès au leurre depuis {ip}.\n"
                    f"Pour la bloquer au pare-feu, réponds : bloque {ip}")

            Honeypot(on_intrusion=_sur_intrusion, port=config.HONEYPOT_PORT).demarrer()
        if config.OREILLE:   # l'ouïe : sons hors champ des caméras (bris de glace, alarme…)
            from hearing import SoundWatcher

            def _sur_son(fr, label, score):
                jarvis.notify_owner(f"👂 {fr.capitalize()} détecté.")
                evidence.consigner(f"son : {fr} ({label} {score:.2f})")
                watchdog.sur_son(fr)   # réaction active si la Sentinelle est armée

            SoundWatcher(_sur_son, seuil=config.OREILLE_SEUIL).demarrer()
    if plugins is not None:
        plugins.attach(jarvis.brain)
        plugins.reload()
        plugins.start()
        proposals.hot_reload = plugins.reload
    if config.MQTT:   # annonces d'arrivée (caméras Frigate/Double Take)
        from arrivals import ArrivalWatcher, texte_arrivee
        from ptz import PtzController, regard_sur_zone
        from skills import JsonStore
        _ptz = PtzController(JsonStore(config.PTZ_FILE, {}))
        _look = cameras.look if cameras is not None else None

        from sightings import journal

        def _sur_arrivee(nom, cam, connu):
            journal().noter(nom, cam, connu)               # mémorise pour « qui as-tu vu ? »
            texte = texte_arrivee(nom, cam, connu)
            if config.AUTO_REGARD and _look is not None:   # oriente la caméra et regarde
                desc = regard_sur_zone(_ptz, _look, cam)
                if desc:
                    texte += f" J'y jette un œil : {desc}"
            jarvis.notify_owner(texte)
            watchdog.sur_intrusion(nom, cam, connu)        # réaction active si armé + inconnu
            # Sur intrusion (armé + inconnu) : filmer la zone et t'envoyer la vidéo.
            if watchdog.arme and not connu and cameras is not None:
                import os as _os
                from camera import grab_clip
                url = cameras.book.find(cam)
                clip = grab_clip(url) if url else None
                if clip:
                    try:
                        jarvis.envoyer(f"🚨 {cam} filmé pendant l'intrusion.", piece_jointe=clip)
                    finally:
                        _os.remove(clip)

        ArrivalWatcher(_sur_arrivee, host=config.MQTT_HOST, port=config.MQTT_PORT,
                       topic=config.MQTT_TOPIC, username=config.MQTT_USER,
                       password=config.MQTT_PASS).demarrer()

    if config.AUDIO_FOLLOW:   # le son suit de pièce en pièce (Snapcast + présence HA)
        from audiofollow import make_audio_follow
        _suivi = make_audio_follow(home)
        if _suivi is not None:
            _suivi.demarrer()

    if config.GLASSES:   # lunettes connectées : la caméra que tu portes interroge Jarvis
        from glasses import demarrer_lunettes
        demarrer_lunettes(gemini)

    if config.POOL:   # surveillance piscine (Frigate -> alarme, baies, escalade urgence)
        from poolguard import make_poolguard
        _piscine = make_poolguard(home, jarvis.notify_owner)
        if _piscine is not None:
            _piscine.demarrer()

    if config.MOWER:   # kill-switch visuel tondeuse (Frigate -> coupe les lames)
        from mower import make_mower_watcher
        _tondeuse = make_mower_watcher(jarvis.notify_owner, home)
        if _tondeuse is not None:
            _tondeuse.demarrer()

    if config.DRONEWATCH:   # veille aérienne (drones Remote ID)
        from dronewatch import make_drone_watcher
        _aerien = make_drone_watcher(jarvis.notify_owner)
        if _aerien is not None:
            _aerien.demarrer()

    if config.CONSCIENCE_PROACTIVE:   # réflexion proactive (fait le point s'il a à dire)
        from conscience import make_conscience_watcher
        _csc = make_conscience_watcher(home, claude, jarvis.notify_owner)
        if _csc is not None:
            _csc.demarrer()

    if config.THERMAL:   # vigilance thermique (plaque de cuisson oubliée)
        from thermal import make_thermal_watcher
        _thermique = make_thermal_watcher(home, jarvis.notify_owner)
        if _thermique is not None:
            _thermique.demarrer()

    if config.HEARTBEAT:   # battement de cœur (détecteur d'homme mort pour la résilience)
        from heartbeat import make_heartbeat
        _coeur = make_heartbeat()
        if _coeur is not None:
            _coeur.demarrer()

    if config.WIFI_STABILITE:   # détection d'instabilité Wi-Fi (symptôme de déauth)
        from wifiwatch import make_wifi_watcher
        _wifi = make_wifi_watcher(jarvis.notify_owner)
        if _wifi is not None:
            _wifi.demarrer()

    if config.STARLINK:   # surveillance de la liaison Internet (coupure, obstruction)
        from starlink import make_starlink_watcher
        _star = make_starlink_watcher(jarvis.notify_owner)
        if _star is not None:
            _star.demarrer()

    if config.OPNSENSE:   # fil d'alarme bastion OPNsense (tentative IoT -> cœur)
        from opnsense import make_opnsense_watcher
        _opn = make_opnsense_watcher(jarvis.notify_owner)
        if _opn is not None:
            _opn.demarrer()

    if config.AGENT and config.IMPROVE_AT:
        NightlyImprover(growth, proposals, claude, at=config.IMPROVE_AT,
                        notify=jarvis.send_proposal).start()

    log.info("Jarvis est en ligne sur Signal (Ctrl+C pour arrêter).")
    try:
        transport.proc.wait()  # type: ignore[union-attr]
    except KeyboardInterrupt:
        log.info("Arrêt de Jarvis Signal.")


if __name__ == "__main__":
    main()
