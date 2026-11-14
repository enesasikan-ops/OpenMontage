"""Canal de commandement Matrix — alertes de Jarvis sur TON propre serveur chiffré.

Au lieu d'envoyer les alertes par Telegram/Signal/WhatsApp (dont les métadonnées — heure,
fréquence, taille des images — transitent par des serveurs tiers), tu héberges ton propre
serveur Matrix (Synapse) et Jarvis y poste sur un salon chiffré de bout en bout. Même ton
fournisseur d'accès ne voit ni à qui tu parles ni ce que le serveur t'envoie.

Ce module ENVOIE (texte + médias : photos/clips Frigate). La logique de routage est
testable (envoi injecté) ; l'envoi réel utilise matrix-nio (chiffrement transparent si
le salon est chiffré et que le compte de Jarvis y est trusté).

Réglages (.env) :
  JARVIS_MATRIX=1
  JARVIS_MATRIX_SERVEUR   https://matrix.ton-domaine.fr
  JARVIS_MATRIX_JETON     jeton d'accès du compte Jarvis (secret)
  JARVIS_MATRIX_SALON     !idDuSalon:ton-domaine.fr
  JARVIS_MATRIX_USER      @jarvis:ton-domaine.fr (facultatif, utile au store E2E)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("jarvis.matrix")

_IMAGES = (".jpg", ".jpeg", ".png", ".gif", ".webp")
_VIDEOS = (".mp4", ".mkv", ".webm", ".mov")


def _type_media(chemin: str) -> str:
    ext = Path(chemin).suffix.lower()
    if ext in _VIDEOS:
        return "m.video"
    if ext in _IMAGES:
        return "m.image"
    return "m.file"


class MatrixNotifier:
    def __init__(self, serveur: str, jeton: str, salon: str, user: str = "",
                 envoi: "Callable | None" = None):
        self.serveur = (serveur or "").rstrip("/")
        self.jeton = jeton
        self.salon = salon
        self.user = user
        self._envoi = envoi      # envoi(texte, chemin|None) -> None ; injecté pour les tests

    @property
    def configure(self) -> bool:
        return bool(self.serveur and self.jeton and self.salon)

    def envoyer(self, texte: str, chemin: "str | None" = None) -> bool:
        """Poste un message (et un média facultatif) sur le salon. Ne lève jamais."""
        if not self.configure:
            log.warning("Matrix non configuré (serveur / jeton / salon)")
            return False
        try:
            (self._envoi or self._nio)(texte, chemin)
            return True
        except Exception:
            log.exception("envoi Matrix")
            return False

    # --- Envoi réel via matrix-nio -------------------------------------------------

    def _nio(self, texte: str, chemin: "str | None") -> None:
        import asyncio
        asyncio.run(self._async(texte, chemin))

    async def _async(self, texte: str, chemin: "str | None") -> None:
        from nio import AsyncClient

        client = AsyncClient(self.serveur, self.user)
        client.access_token = self.jeton
        try:
            if chemin:
                await self._envoyer_media(client, chemin, texte)
            else:
                await client.room_send(self.salon, "m.room.message",
                                       {"msgtype": "m.text", "body": texte})
        finally:
            await client.close()

    async def _envoyer_media(self, client, chemin: str, legende: str) -> None:
        import aiofiles
        import aiofiles.os

        taille = (await aiofiles.os.stat(chemin)).st_size
        async with aiofiles.open(chemin, "rb") as f:
            reponse, _ = await client.upload(f, content_type="application/octet-stream",
                                             filename=Path(chemin).name, filesize=taille)
        await client.room_send(self.salon, "m.room.message", {
            "msgtype": _type_media(chemin),
            "body": legende or Path(chemin).name,
            "url": reponse.content_uri,
        })


def make_matrix_notifier() -> "MatrixNotifier | None":
    import config
    if not config.MATRIX:
        return None
    n = MatrixNotifier(config.MATRIX_SERVEUR, config.MATRIX_JETON, config.MATRIX_SALON,
                       user=config.MATRIX_USER)
    return n if n.configure else None
