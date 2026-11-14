"""Consolidation de mémoire — le « sommeil cognitif », version honnête.

Le cerveau, la nuit, ne change pas son câblage pour agir tout seul : il RANGE et il
OUBLIE. C'est ça qu'on imite ici, et rien de plus mythique.

DEUX FANTASMES ÉCARTÉS (dits franchement) :
- « Jarvis modifie ses propres poids synaptiques » : non. GraphRAG / Mem0 ne ré-entraînent
  pas le modèle ; ils construisent une MÉMOIRE externe. Les poids du modèle restent gelés.
  L'« intuition », c'est de la récupération dans une mémoire structurée, pas des neurones
  modifiés. Prétendre le contraire, c'est du vernis.
- « Le lendemain, sans directive, il tamise la lumière tout seul » : une corrélation
  « 3 fois cette semaine » est un signal FAIBLE, souvent fortuit. Agir seul là-dessus, non.
  Ce comportement-là existe déjà, fait proprement, dans habits.py : il PROPOSE, tu valides.

Ce que fait ce module : la nuit, il relit les faits mémorisés et PROPOSE une version
consolidée (fusionne les doublons, oublie le trivial et l'éphémère, garde le durable).
Rien n'est réécrit sans ton accord — on ne réinvente pas ta mémoire en douce.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger("jarvis.consolidation")

PROMPT = """Voici les faits que Jarvis a mémorisés sur l'utilisateur :

{faits}

Consolide-les, comme une nuit de sommeil range la mémoire :
- fusionne les doublons et les redondances en un fait clair ;
- supprime le trivial et l'éphémère (un relevé ponctuel, une broutille sans lendemain) ;
- garde ce qui est durable et utile (préférences, infos personnelles, projets).

Règles impératives :
- N'INVENTE aucun fait nouveau et ne déduis aucun comportement à automatiser.
- Ne supprime pas une information personnelle importante par excès de zèle.

Réponds UNIQUEMENT en JSON : {{"faits": ["...liste consolidée..."], "changements": "résumé en une phrase"}}"""


def _extraire_json(texte: str) -> "dict | None":
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut == -1 or fin <= debut:
        return None
    try:
        return json.loads(texte[debut:fin + 1])
    except json.JSONDecodeError:
        return None


class ConsolidationManager:
    def __init__(self, memory, demander):
        self.memory = memory
        self.demander = demander          # demander(question, contexte) -> str (renfort)
        self._propose: "list | None" = None
        self._resume = ""

    def proposer(self) -> str:
        faits = list(self.memory.facts)
        if not faits:
            self._propose = None
            return "Il n'y a rien à consolider : la mémoire est vide."
        try:
            reponse = self.demander(PROMPT.format(faits="\n".join(f"- {f}" for f in faits)), "")
        except Exception:
            log.exception("consolidation : renfort")
            return "Je n'ai pas pu préparer la consolidation (renfort indisponible)."
        data = _extraire_json(reponse)
        nouveaux = data.get("faits") if isinstance(data, dict) else None
        if not isinstance(nouveaux, list) or not all(isinstance(x, str) for x in nouveaux):
            return "La consolidation a échoué (réponse illisible) ; je ne touche à rien."
        nouveaux = [x.strip() for x in nouveaux if x.strip()]
        if faits and not nouveaux:        # garde-fou : jamais vider une mémoire non vide
            return "La consolidation proposait de tout effacer ; je refuse et garde la mémoire intacte."
        self._propose = nouveaux
        self._resume = (data.get("changements") if isinstance(data, dict) else "") or ""
        perdus = len(faits) - len(nouveaux)
        detail = f" ({self._resume})" if self._resume else ""
        return (f"Consolidation proposée : {len(faits)} faits → {len(nouveaux)}{detail}. "
                "Dites oui pour l'appliquer, sinon je garde la mémoire telle quelle.")

    def appliquer(self) -> str:
        if self._propose is None:
            return self.proposer()        # pas encore de proposition : on la prépare d'abord
        self.memory.facts = list(self._propose)
        self.memory._save()
        n = len(self.memory.facts)
        self._propose = None
        return f"Mémoire consolidée : {n} faits conservés."


def build_consolidation_tools(memory, renfort) -> list:
    from tools import Tool

    ask = getattr(renfort, "ask", None)
    if not (callable(ask) and getattr(renfort, "available", False)):
        return []   # la consolidation s'appuie sur un bon raisonneur (renfort)
    mgr = ConsolidationManager(memory, ask)

    return [Tool(
        name="consolider_memoire",
        description=("Range et nettoie la mémoire (« sommeil cognitif ») : fusionne les "
                     "doublons, oublie le trivial, garde le durable. PROPOSE d'abord, "
                     "n'applique qu'après ton accord. « consolide ta mémoire »."),
        parameters={"type": "object", "properties": {}, "required": []},
        run=lambda: mgr.appliquer(),
        confirm=lambda: mgr.proposer(),
    )]
