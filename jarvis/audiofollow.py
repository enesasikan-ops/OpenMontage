"""Le son qui marche avec toi — Snapcast + présence Home Assistant.

Snapcast diffuse un flux audio PARFAITEMENT synchronisé sur plusieurs enceintes (des
Raspberry Pi, par ex.). Lui gère la synchro ; Jarvis, lui, ne fait que **router le
volume** selon où tu te trouves : la pièce que tu occupes monte, les autres baissent.
Tu lances un podcast dans la cuisine, tu passes au salon → le son te suit.

La présence vient de Home Assistant (radars mmWave, caméras Frigate… exposés en
`binary_sensor`). On raisonne par ENSEMBLE de pièces occupées : s'il y a du monde dans
deux pièces, les deux restent audibles — pas de bagarre « quelle est MA pièce ».

Deux backends pour régler le volume, même interface :
- Home Assistant (défaut) : chaque enceinte est un `media_player` (volume_set) ;
- Snapcast direct (JSON-RPC) : `Client.SetVolume` sur le snapserver.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable

import config
import persona

log = logging.getLogger(__name__)

JOUE = ("playing", "buffering")


@dataclass(frozen=True)
class Piece:
    nom: str
    presence: str      # entity_id du capteur de présence (binary_sensor)
    enceinte: str      # media_player (backend HA) ou nom du client Snapcast


def pieces_config() -> list:
    out = []
    for nom, d in (config.AUDIO_PIECES or {}).items():
        if isinstance(d, dict) and d.get("enceinte"):
            out.append(Piece(nom=nom, presence=d.get("presence", ""), enceinte=d["enceinte"]))
    return out


def niveaux_cibles(pieces: list, occupees: set, present: float, absent: float) -> dict:
    """Volume visé par pièce : `present` si occupée, `absent` sinon."""
    return {p.nom: (present if p.nom in occupees else absent) for p in pieces}


# --- Contrôleur : applique les niveaux, sans appels redondants ----------------------


class AudioFollow:
    def __init__(self, pieces: list, regler: "Callable[[str, float], None]",
                 present: float = 0.35, absent: float = 0.0):
        self.pieces = list(pieces)
        self.regler = regler            # regler(enceinte, niveau 0..1)
        self.present = present
        self.absent = absent
        self.actif = False
        self._applique: dict = {}       # dernier niveau posé par pièce

    def _appliquer(self, cibles: dict) -> dict:
        changes = {}
        for p in self.pieces:
            niveau = cibles[p.nom]
            if self._applique.get(p.nom) == niveau:
                continue
            try:
                self.regler(p.enceinte, niveau)
            except Exception:
                log.exception("réglage du volume (%s)", p.nom)
                continue
            self._applique[p.nom] = niveau
            changes[p.nom] = niveau
        return changes

    def router(self, occupees, joue: bool = True) -> dict:
        """Suivi automatique : ne fait rien si inactif, ou si rien ne joue."""
        if not self.actif or not self.pieces or not joue:
            return {}
        return self._appliquer(niveaux_cibles(self.pieces, set(occupees), self.present, self.absent))

    def vers(self, cibles_noms) -> dict:
        """Commande explicite (« mets le son dans le salon ») : s'applique quoi qu'il arrive."""
        cibles = {n.lower() for n in cibles_noms}
        voulu = {p.nom: (self.present if p.nom.lower() in cibles else self.absent) for p in self.pieces}
        return self._appliquer(voulu)

    def activer(self) -> None:
        self.actif = True
        self._applique = {}

    def arreter(self) -> None:
        self.actif = False     # cesse de router ; ne touche pas aux volumes en place


# --- Backend Snapcast direct (JSON-RPC sur le snapserver) ---------------------------


class Snapcast:
    def __init__(self, host: str, port: int = 1705,
                 transport: "Callable | None" = None):
        self.host, self.port = host, port
        self._transport = transport     # transport(requete) -> reponse (injecté pour les tests)

    def _rpc(self, method: str, params: "dict | None" = None) -> dict:
        req = {"id": 1, "jsonrpc": "2.0", "method": method, "params": params or {}}
        if self._transport is not None:
            return self._transport(req)
        return self._tcp(req)

    def _tcp(self, req: dict) -> dict:
        import socket

        with socket.create_connection((self.host, self.port), timeout=5) as s:
            s.sendall((json.dumps(req) + "\r\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode("utf-8").strip() or "{}")

    def clients(self) -> dict:
        """Nom du client -> id, d'après Server.GetStatus."""
        status = self._rpc("Server.GetStatus")
        out = {}
        server = (status.get("result", {}) or {}).get("server", {})
        for groupe in server.get("groups", []):
            for c in groupe.get("clients", []):
                nom = (c.get("config", {}).get("name")
                       or c.get("host", {}).get("name") or c.get("id"))
                if nom:
                    out[nom] = c.get("id")
        return out

    def set_volume(self, client_id: str, pct: int) -> None:
        self._rpc("Client.SetVolume",
                  {"id": client_id, "volume": {"percent": int(pct), "muted": pct <= 0}})


def _setter(home) -> "Callable[[str, float], None]":
    if config.SNAPSERVER:
        snap = Snapcast(config.SNAPSERVER, config.SNAPSERVER_PORT)
        cache: dict = {}

        def regler(enceinte: str, niveau: float) -> None:
            if not cache:
                try:
                    cache.update(snap.clients())
                except Exception:
                    log.exception("Snapcast GetStatus")
            snap.set_volume(cache.get(enceinte, enceinte), round(niveau * 100))

        return regler

    def regler(enceinte: str, niveau: float) -> None:
        home.call("media_player", "volume_set", enceinte, volume_level=round(niveau, 3))

    return regler


# Contrôleur partagé entre les outils vocaux et le suivi automatique.
_CTRL: "AudioFollow | None" = None


def controleur(home) -> "AudioFollow | None":
    global _CTRL
    if _CTRL is None:
        pieces = pieces_config()
        if not pieces:
            return None
        _CTRL = AudioFollow(pieces, _setter(home),
                            present=config.AUDIO_PRESENT, absent=config.AUDIO_ABSENT)
    return _CTRL


# --- Veille de présence (suivi automatique) -----------------------------------------


class PresenceAudioWatcher(threading.Thread):
    def __init__(self, home, controleur: AudioFollow, pieces: list, interval_s: float = 3.0):
        super().__init__(daemon=True, name="jarvis-audio-suivi")
        self.home = home
        self.controleur = controleur
        self.pieces = pieces
        self.interval_s = interval_s
        self._halt = threading.Event()

    def un_tour(self) -> dict:
        try:
            etats = {e["entity_id"]: e.get("state") for e in self.home.states()}
        except Exception:
            log.exception("lecture des capteurs de présence")
            return {}
        occupees = {p.nom for p in self.pieces if etats.get(p.presence) == "on"}
        joue = any(etats.get(p.enceinte) in JOUE for p in self.pieces)
        return self.controleur.router(occupees, joue)

    def demarrer(self) -> None:
        self.start()

    def run(self) -> None:
        while not self._halt.wait(self.interval_s):
            self.un_tour()

    def arreter(self) -> None:
        self._halt.set()


def make_audio_follow(home) -> "PresenceAudioWatcher | None":
    if not config.AUDIO_FOLLOW:
        return None
    ctrl = controleur(home)
    if ctrl is None:
        return None
    ctrl.activer()        # en mode auto, le suivi est actif dès le départ
    return PresenceAudioWatcher(home, ctrl, ctrl.pieces, interval_s=config.AUDIO_INTERVAL)


# --- Outils vocaux ------------------------------------------------------------------


def build_audio_tools(home) -> list:
    from tools import Tool

    if not config.AUDIO_PIECES:
        return []
    ctrl = controleur(home)
    if ctrl is None:
        return []
    titre = persona.title()
    noms = ", ".join(p.nom for p in ctrl.pieces)

    def suivez_moi() -> str:
        ctrl.activer()
        return f"Entendu, {titre} : le son vous suivra de pièce en pièce."

    def arrete_de_suivre() -> str:
        ctrl.arreter()
        return "Je cesse de faire suivre le son ; les volumes restent tels quels."

    def son_dans(piece: str) -> str:
        cibles = [p.nom for p in ctrl.pieces if p.nom.lower() == (piece or "").strip().lower()]
        if not cibles:
            return f"Je ne connais pas la pièce « {piece} ». Pièces configurées : {noms}."
        ctrl.vers(set(cibles))
        return f"Le son est pour {cibles[0]}, {titre}."

    return [
        Tool(name="suivez_moi",
             description=("Active le suivi audio : le son monte dans la pièce où tu es et baisse "
                          "dans les autres (« que le son me suive », « suivez-moi »)."),
             parameters={"type": "object", "properties": {}, "required": []},
             run=suivez_moi),
        Tool(name="arrete_de_suivre",
             description="Désactive le suivi audio de pièce en pièce.",
             parameters={"type": "object", "properties": {}, "required": []},
             run=arrete_de_suivre),
        Tool(name="son_dans_la_piece",
             description=("Envoie le son dans une pièce précise maintenant (« mets le son dans "
                          "le salon », « le son dans la cuisine »)."),
             parameters={"type": "object",
                         "properties": {"piece": {"type": "string", "description": "la pièce visée"}},
                         "required": ["piece"]},
             run=son_dans),
    ]
