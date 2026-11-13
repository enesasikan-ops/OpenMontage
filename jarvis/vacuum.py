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

    def _entite(self) -> "str | None":
        for e in self.home.states():
            if e["entity_id"].startswith("vacuum."):
                return e["entity_id"]
        return None

    def _segment(self, zone: str) -> "str | None":
        z = _norm(zone)
        if z in self.segments:
            return self.segments[z]
        for nom, seg in self.segments.items():     # correspondance souple (« canapé du salon »)
            if nom in z or z in nom:
                return seg
        return None

    def aspirer(self, zone: str = "") -> str:
        ent = self._entite()
        if ent is None:
            return "Je ne trouve pas d'aspirateur connecté."
        if not _norm(zone):
            self.home.call("vacuum", "start", ent)
            return "Je lance le ménage, Monsieur."
        seg = self._segment(zone)
        if seg is None:
            connues = ", ".join(sorted(self.segments)) or "aucune pièce configurée"
            return f"Je ne sais pas où est « {zone} ». Pièces connues : {connues}."
        self.home.call("vacuum", "send_command", ent,
                       command=self.segment_cmd, params={"segment_ids": [seg]})
        return f"Je nettoie {zone}, Monsieur."

    def arreter(self) -> str:
        ent = self._entite()
        if ent is None:
            return "Je ne trouve pas d'aspirateur connecté."
        self.home.call("vacuum", "stop", ent)
        return "J'arrête l'aspirateur."

    def retour_base(self) -> str:
        ent = self._entite()
        if ent is None:
            return "Je ne trouve pas d'aspirateur connecté."
        self.home.call("vacuum", "return_to_base", ent)
        return "L'aspirateur rentre à sa base."

    def etat(self) -> str:
        for e in self.home.states():
            if e["entity_id"].startswith("vacuum."):
                nom = e.get("attributes", {}).get("friendly_name", "L'aspirateur")
                batt = e.get("attributes", {}).get("battery_level")
                suffixe = f", batterie {batt}%" if batt is not None else ""
                return f"{nom} : {e.get('state', 'inconnu')}{suffixe}."
        return "Je ne trouve pas d'aspirateur connecté."


def build_vacuum_tools(home, segments: dict | None = None) -> list:
    from tools import Tool

    v = VacuumControl(home, segments if segments is not None else config.VACUUM_SEGMENTS)
    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    return [
        Tool(name="aspirer",
             description=("Lance l'aspirateur robot. Sans pièce : ménage complet. Avec une pièce "
                          "(salon, cuisine…) : nettoie seulement cette zone."),
             parameters=obj({"zone": {**s, "description": "la pièce à nettoyer (vide = tout)"}}, []),
             run=lambda zone="": v.aspirer(zone)),
        Tool(name="arreter_aspirateur", description="Arrête l'aspirateur robot.",
             parameters=obj({}, []), run=lambda: v.arreter()),
        Tool(name="renvoyer_aspirateur", description="Renvoie l'aspirateur à sa base de charge.",
             parameters=obj({}, []), run=lambda: v.retour_base()),
        Tool(name="etat_aspirateur", description="État de l'aspirateur (en charge, en cours, batterie).",
             parameters=obj({}, []), run=lambda: v.etat()),
    ]
