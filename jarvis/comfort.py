"""Ambiances de confort (détente), déclenchées par toi, pas devinées.

« Jarvis, mode détente » → baisse les lumières, met une musique douce. Fiable et sous ton
contrôle — pas de lecture d'émotion sur ton visage ou ta voix (peu fiable et intrusif).
"""

from __future__ import annotations

import config


class Comfort:
    def __init__(self, home):
        self.home = home

    def detente(self, niveau: "int | None" = None) -> str:
        lumieres = config.DETENTE_LUMIERES
        media = config.DETENTE_MEDIA
        if not lumieres and not media:
            return "Le mode détente n'est pas configuré (JARVIS_DETENTE_LUMIERES / _MEDIA)."
        pct = int(niveau) if niveau is not None else config.DETENTE_NIVEAU
        pct = max(1, min(pct, 100))
        faits = []
        if lumieres:
            try:
                self.home.call("light", "turn_on", list(lumieres), brightness_pct=pct)
                faits.append(f"lumières à {pct} %")
            except Exception:
                pass
        if media and config.DETENTE_SOURCE:
            try:
                self.home.call("media_player", "play_media", media,
                               media_content_id=config.DETENTE_SOURCE, media_content_type="music")
                faits.append("musique douce")
            except Exception:
                pass
        elif media:
            try:
                self.home.call("media_player", "media_play", media)
                faits.append("musique")
            except Exception:
                pass
        if not faits:
            return "Je n'ai pas réussi à lancer l'ambiance détente."
        return "Ambiance détente, Monsieur : " + ", ".join(faits) + "."


def build_comfort_tools(home) -> list:
    from tools import Tool

    if not (config.DETENTE_LUMIERES or config.DETENTE_MEDIA):
        return []
    c = Comfort(home)
    return [Tool(
        name="mode_detente",
        description=("Lance une ambiance apaisante : baisse les lumières et met une musique douce "
                     "(« mode détente », « je suis crevé », « ambiance cocooning »)."),
        parameters={"type": "object",
                    "properties": {"niveau": {"type": "number",
                                   "description": "luminosité en % (défaut configuré)"}},
                    "required": []},
        run=lambda niveau=None: c.detente(niveau),
    )]
