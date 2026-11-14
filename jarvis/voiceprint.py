"""Authentification par empreinte vocale — qui a le droit de commander quoi.

Ton enfant crie « Jarvis, désactive l'alarme et ouvre le portail ». Jarvis compare
l'empreinte de la voix à la tienne : elle ne correspond pas → « Accès refusé. Niveau
d'autorisation insuffisant. » Toi, même phrase, et le portail s'ouvre.

HONNÊTETÉ (c'est de la sécurité, pas de la magie) :
- La biométrie vocale est un FACTEUR, pas un coffre-fort. Un enregistrement de ta voix
  (attaque par rejeu) ou un très bon imitateur peut tromper le système : c'est un score
  de similarité avec un seuil, donc probabiliste.
- Donc on échoue FERMÉ : au moindre doute (voix non reconnue, pas de son, moteur absent),
  on REFUSE — jamais on n'ouvre « dans le doute ».
- Et on garde une PORTE DE SECOURS : un code maître débloque une courte fenêtre, pour que
  Jarvis ne t'enferme jamais dehors si ta voix est mal reconnue (bruit, rhume, cri).
- Tout est local : les empreintes ne quittent pas la maison. On n'enregistre que les
  personnes qui se sont enrôlées volontairement.
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path
from typing import Callable

import config

log = logging.getLogger("jarvis.voix")

REFUS = "Accès refusé. Niveau d'autorisation insuffisant."


def cosine(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return num / (na * nb) if na and nb else 0.0


class VoiceStore:
    """Empreintes vocales enrôlées, sur le disque local : {nom: [[floats], ...]}."""

    def __init__(self, chemin: Path):
        self.chemin = Path(chemin)
        self._data: dict = {}
        if self.chemin.exists():
            try:
                self._data = json.loads(self.chemin.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                log.warning("empreintes illisibles, on repart à vide")

    def ajouter(self, nom: str, empreinte: list) -> None:
        self._data.setdefault(nom, []).append(list(empreinte))
        self._sauver()

    def empreintes(self, nom: str) -> list:
        return self._data.get(nom, [])

    def noms(self) -> list:
        return list(self._data)

    def oublier(self, nom: str) -> bool:
        existe = nom in self._data
        self._data.pop(nom, None)
        self._sauver()
        return existe

    def _sauver(self) -> None:
        try:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            self.chemin.write_text(json.dumps(self._data), "utf-8")
        except OSError:
            log.exception("sauvegarde des empreintes")


# --- Empreinte à partir du son (SpeechBrain ECAPA, chargé tardivement) ---------------


def _ecapa_embed(audio) -> list:
    """Empreinte ECAPA-TDNN (SpeechBrain). audio = float32 mono 16 kHz."""
    import torch  # lourd : importé seulement si on utilise la vraie vérification
    from speechbrain.inference.speaker import EncoderClassifier

    global _ECAPA
    try:
        _ECAPA
    except NameError:
        _ECAPA = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            savedir=str(config.DATA_DIR / "modeles" / "ecapa"))
    signal = torch.tensor(audio).float().unsqueeze(0)
    emb = _ECAPA.encode_batch(signal).squeeze().detach().cpu().tolist()
    return emb


class SpeakerVerifier:
    def __init__(self, store: VoiceStore, embed: "Callable | None" = None, seuil: float = 0.65):
        self.store = store
        self._embed = embed or _ecapa_embed
        self.seuil = seuil

    def empreinte(self, audio) -> list:
        return self._embed(audio)

    def enroler(self, nom: str, audios: list) -> int:
        n = 0
        for audio in audios:
            if audio is not None and len(audio):
                self.store.ajouter(nom, self.empreinte(audio))
                n += 1
        return n

    def verifier(self, audio, nom: str) -> "tuple[bool, float]":
        """L'audio correspond-il à l'empreinte de `nom` ?"""
        empreintes = self.store.empreintes(nom)
        if not empreintes or audio is None or not len(audio):
            return (False, 0.0)
        emb = self.empreinte(audio)
        score = max(cosine(emb, e) for e in empreintes)
        return (score >= self.seuil, score)

    def identifier(self, audio) -> "tuple[str | None, float]":
        """Qui parle ? Meilleur enrôlé au-dessus du seuil, sinon None."""
        if audio is None or not len(audio):
            return (None, 0.0)
        emb = self.empreinte(audio)
        meilleur, score = None, -1.0
        for nom in self.store.noms():
            s = max((cosine(emb, e) for e in self.store.empreintes(nom)), default=-1.0)
            if s > score:
                meilleur, score = nom, s
        return (meilleur if score >= self.seuil else None, max(score, 0.0))


# --- Garde : décide d'autoriser une action sensible ----------------------------------


class SpeakerGuard:
    def __init__(self, verifier: SpeakerVerifier, proprietaire: str,
                 source: "Callable | None" = None, code: str = "",
                 fenetre_s: float = 60.0, horloge: "Callable[[], float]" = time.monotonic):
        self.verifier = verifier
        self.proprietaire = proprietaire
        self.source = source or (lambda: None)   # -> audio de la commande en cours
        self.code = code
        self.fenetre_s = fenetre_s
        self.horloge = horloge
        self._debloque_jusqu = -1e18

    def _fenetre_ouverte(self) -> bool:
        return self.horloge() < self._debloque_jusqu

    def deverrouiller(self, code: str) -> str:
        """Porte de secours : un code maître ouvre une courte fenêtre d'autorisation."""
        if not self.code:
            return "Aucun code maître n'est configuré."
        if code.strip() == self.code:
            self._debloque_jusqu = self.horloge() + self.fenetre_s
            return f"Code accepté, {persona_titre()}. Vous avez {int(self.fenetre_s)} secondes."
        return REFUS

    def autorise(self) -> "tuple[bool, str]":
        """True si l'action sensible peut passer. Échoue FERMÉ."""
        if self._fenetre_ouverte():
            return (True, "")
        audio = self.source()
        ok, _ = self.verifier.verifier(audio, self.proprietaire)
        if ok:
            return (True, "")
        suite = " Dites votre code maître pour confirmer." if self.code else ""
        return (False, REFUS + suite)


def persona_titre() -> str:
    try:
        import persona
        return persona.title()
    except Exception:
        return "Monsieur"


# --- Protection des outils sensibles -------------------------------------------------


def proteger_outils(tools: dict, guard: SpeakerGuard, noms_proteges) -> list:
    """Enveloppe les outils protégés : ils vérifient l'identité AVANT d'agir.

    Renvoie la liste des noms effectivement protégés. Modifie `tools` en place.
    """
    import dataclasses

    protiges = []
    for nom in noms_proteges:
        outil = tools.get(nom)
        if outil is None:
            continue
        run_original = outil.run

        def garde(*args, _run=run_original, **kwargs):
            ok, message = guard.autorise()
            if not ok:
                return message
            return _run(*args, **kwargs)

        tools[nom] = dataclasses.replace(outil, run=garde)
        protiges.append(nom)
    return protiges


def build_voice_tools(guard: SpeakerGuard) -> list:
    from tools import Tool

    outils = [Tool(
        name="code_maitre",
        description=("Débloque les actions sensibles avec le code maître si ta voix est mal "
                     "reconnue (porte de secours). À utiliser quand tu dis ton code."),
        parameters={"type": "object",
                    "properties": {"code": {"type": "string", "description": "le code maître"}},
                    "required": ["code"]},
        run=lambda code: guard.deverrouiller(code),
    )]
    return outils


# --- Fabrique depuis la config -------------------------------------------------------


def make_guard(source: "Callable | None" = None,
               embed: "Callable | None" = None) -> "SpeakerGuard | None":
    if not config.VOICE_AUTH:
        return None
    store = VoiceStore(config.VOICE_FILE)
    if not store.empreintes(config.VOICE_OWNER):
        log.warning("Auth vocale activée mais aucune empreinte pour « %s » : "
                    "enrôle-toi (python enroll_voice.py). En attendant, auth vocale inactive.",
                    config.VOICE_OWNER)
        return None
    verifier = SpeakerVerifier(store, embed=embed, seuil=config.VOICE_SEUIL)
    return SpeakerGuard(verifier, config.VOICE_OWNER, source=source,
                        code=config.VOICE_PIN, fenetre_s=config.VOICE_FENETRE)
