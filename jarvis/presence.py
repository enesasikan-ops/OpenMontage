"""Carte de présence — quelles pièces sont occupées (anonyme, chez toi).

Jarvis ne sait pas QUI est là, seulement QU'une pièce est occupée. La source d'occupation
lui est égale : capteur PIR, radar mmWave, ou présence par Wi-Fi (ESP32-CSI). Pour Jarvis,
le CSI n'est qu'un `binary_sensor` de plus — tout le traitement du signal reste sur l'ESP32,
qui publie « occupé / vide » à Home Assistant.

LIGNE VOLONTAIRE (et non négociable ici) :
- On raisonne en OCCUPATION BINAIRE et ANONYME d'une pièce, chez le propriétaire. Pas
  d'identification d'une personne, pas de suivi « qui va où », pas de respiration ni de
  signe vital. Ces usages — surtout via un capteur invisible, à l'insu d'un invité, d'un
  proche ou d'un voisin dont le mur est traversé — relèvent de la surveillance et ne sont
  pas construits ici.
- Utile et sobre : savoir qu'une pièce est occupée (ou que la maison est vide) pour
  allumer, suivre le son, armer une vigilance. Rien de plus.
"""

from __future__ import annotations

import config

OCCUPE = ("on", "true", "occupied", "home", "detected")


def pieces_config() -> dict:
    """{nom de pièce: entity_id du capteur d'occupation}."""
    return {nom: ent for nom, ent in (config.PRESENCE_PIECES or {}).items()
            if isinstance(ent, str) and ent}


def _occupee(valeur) -> bool:
    return str(valeur).strip().lower() in OCCUPE


def occupees(etats: dict, pieces: dict) -> set:
    return {nom for nom, ent in pieces.items() if _occupee(etats.get(ent))}


def maison_vide(etats: dict, pieces: dict) -> bool:
    """True si AUCUNE pièce connue n'est occupée (et qu'on a bien des pièces à regarder)."""
    return bool(pieces) and not occupees(etats, pieces)


def build_presence_tools(home) -> list:
    from tools import Tool

    pieces = pieces_config()
    if not pieces:
        return []

    def _etats() -> dict:
        try:
            return {e["entity_id"]: e.get("state") for e in home.states()}
        except Exception:
            return {}

    def ou_y_a_t_il_du_monde() -> str:
        occ = sorted(occupees(_etats(), pieces))
        if not occ:
            return "Aucune pièce surveillée n'est occupée pour l'instant."
        return "Pièces occupées : " + ", ".join(occ) + "."

    def piece_occupee(piece: str) -> str:
        cible = [n for n in pieces if n.lower() == (piece or "").strip().lower()]
        if not cible:
            return f"Je ne surveille pas la pièce « {piece} ». Pièces : {', '.join(pieces)}."
        nom = cible[0]
        occ = nom in occupees(_etats(), pieces)
        return f"{nom.capitalize()} : {'occupée' if occ else 'vide'}."

    def la_maison_est_elle_vide() -> str:
        etats = _etats()
        if maison_vide(etats, pieces):
            return "La maison semble vide : aucune pièce surveillée n'est occupée."
        return "Il y a du monde : " + ", ".join(sorted(occupees(etats, pieces))) + "."

    vide = {"type": "object", "properties": {}, "required": []}
    return [
        Tool(name="pieces_occupees",
             description=("Dit quelles pièces sont occupées en ce moment (capteurs de présence, "
                          "y compris présence Wi-Fi). Anonyme : qui, non ; occupé ou vide, oui."),
             parameters=vide, run=ou_y_a_t_il_du_monde),
        Tool(name="piece_occupee",
             description="Dit si une pièce précise est occupée ou vide.",
             parameters={"type": "object",
                         "properties": {"piece": {"type": "string", "description": "la pièce"}},
                         "required": ["piece"]},
             run=piece_occupee),
        Tool(name="maison_vide",
             description="Dit si la maison est vide (aucune pièce occupée). Utile avant d'armer une vigilance.",
             parameters=vide, run=la_maison_est_elle_vide),
    ]
