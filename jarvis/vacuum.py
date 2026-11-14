"""Contrôle de l'aspirateur robot (via Home Assistant / Valetudo, en local).

« Jarvis, aspire le salon » / « renvoie l'aspirateur à sa base ». L'aspirateur dé-cloudé
(Valetudo) apparaît comme une entité vacuum dans Home Assistant ; Jarvis appelle ses
services. Le nettoyage par pièce utilise les « segments » Valetudo, à associer aux noms
de pièces dans la config (JARVIS_ASPIRATEUR_PIECES).
"""

from __future__ import annotations

import config


def _norm(t: str) -> str:
    return (t or "").strip().lower()


class VacuumControl:
    def __init__(self, home, segments: dict | None = None, segment_cmd: str = "segment_clean"):
        self.home = home
        self.segments = {_norm(k): str(v) for k, v in (segments or {}).items()}
        self.segment_cmd = segment_cmd

    def _etats_aspi(self) -> list:
        return [e for e in self.home.states() if e["entity_id"].startswith("vacuum.")]

    def _nom(self, e: dict) -> str:
        return e.get("attributes", {}).get("friendly_name", e["entity_id"])

    def _cibler(self, nom: str = "") -> list:
        """Les entités visées : toutes, ou celles dont le nom correspond à `nom`."""
        aspis = self._etats_aspi()
        if not _norm(nom):
            return [e["entity_id"] for e in aspis]
        n = _norm(nom)
        return [e["entity_id"] for e in aspis if n in _norm(self._nom(e))]

    def _entite(self) -> "str | None":
        aspis = self._etats_aspi()
        return aspis[0]["entity_id"] if aspis else None

    def _segment(self, zone: str) -> "str | None":
        z = _norm(zone)
        if z in self.segments:
            return self.segments[z]
        for nom, seg in self.segments.items():     # correspondance souple (« canapé du salon »)
            if nom in z or z in nom:
                return seg
        return None

    def aspirer(self, zone: str = "", nom: str = "") -> str:
        cibles = self._cibler(nom)
        if not cibles:
            return (f"Je ne trouve pas d'aspirateur « {nom} »." if _norm(nom)
                    else "Je ne trouve pas d'aspirateur connecté.")
        if not _norm(zone):
            for ent in cibles:
                self.home.call("vacuum", "start", ent)
            combien = f" ({len(cibles)} aspirateurs)" if len(cibles) > 1 and not _norm(nom) else ""
            return f"Je lance le ménage{combien}, Monsieur."
        seg = self._segment(zone)
        if seg is None:
            connues = ", ".join(sorted(self.segments)) or "aucune pièce configurée"
            return f"Je ne sais pas où est « {zone} ». Pièces connues : {connues}."
        self.home.call("vacuum", "send_command", cibles[0],
                       command=self.segment_cmd, params={"segment_ids": [seg]})
        return f"Je nettoie {zone}, Monsieur."

    def arreter(self, nom: str = "") -> str:
        cibles = self._cibler(nom)
        if not cibles:
            return "Je ne trouve pas d'aspirateur connecté."
        for ent in cibles:
            self.home.call("vacuum", "stop", ent)
        return "J'arrête l'aspirateur." if len(cibles) == 1 else f"J'arrête les {len(cibles)} aspirateurs."

    def retour_base(self, nom: str = "") -> str:
        cibles = self._cibler(nom)
        if not cibles:
            return "Je ne trouve pas d'aspirateur connecté."
        for ent in cibles:
            self.home.call("vacuum", "return_to_base", ent)
        return "L'aspirateur rentre à sa base." if len(cibles) == 1 else "Les aspirateurs rentrent à leur base."

    def etat(self, nom: str = "") -> str:
        aspis = self._etats_aspi()
        if _norm(nom):
            aspis = [e for e in aspis if _norm(nom) in _norm(self._nom(e))]
        if not aspis:
            return "Je ne trouve pas d'aspirateur connecté."
        lignes = []
        for e in aspis:
            batt = e.get("attributes", {}).get("battery_level")
            suffixe = f", batterie {batt}%" if batt is not None else ""
            lignes.append(f"{self._nom(e)} : {e.get('state', 'inconnu')}{suffixe}")
        return (lignes[0] + ".") if len(lignes) == 1 else " ; ".join(lignes) + "."


def build_vacuum_tools(home, segments: dict | None = None) -> list:
    from tools import Tool

    v = VacuumControl(home, segments if segments is not None else config.VACUUM_SEGMENTS)
    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    nom_p = {"nom": {**s, "description": "quel aspirateur si plusieurs (ex. « haut », « salon ») ; vide = tous"}}
    return [
        Tool(name="aspirer",
             description=("Lance l'aspirateur robot. Sans pièce : ménage complet. Avec une pièce "
                          "(salon, cuisine…) : nettoie seulement cette zone. Si plusieurs robots, "
                          "précise lequel avec « nom » (sinon tous pour le ménage complet)."),
             parameters=obj({"zone": {**s, "description": "la pièce à nettoyer (vide = tout)"}, **nom_p}, []),
             run=lambda zone="", nom="": v.aspirer(zone, nom)),
        Tool(name="arreter_aspirateur", description="Arrête l'aspirateur robot (tous, ou celui nommé).",
             parameters=obj({**nom_p}, []), run=lambda nom="": v.arreter(nom)),
        Tool(name="renvoyer_aspirateur", description="Renvoie l'aspirateur à sa base (tous, ou celui nommé).",
             parameters=obj({**nom_p}, []), run=lambda nom="": v.retour_base(nom)),
        Tool(name="etat_aspirateur", description="État de l'aspirateur / des aspirateurs (en charge, en cours, batterie).",
             parameters=obj({**nom_p}, []), run=lambda nom="": v.etat(nom)),
    ]
