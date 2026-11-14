"""Planificateur multi-angles — la bonne part du « conseil d'agents », sans le vernis.

Pour une demande complexe (« prépare la maison pour une tempête de 3 jours »), Jarvis ne
lance pas 4 agents sur un cluster qui débattent « à la vitesse de la lumière » pour pondre
un plan « infaillible » (ça n'existe pas : des LLM partagent les mêmes angles morts et
peuvent se tromper de concert). Il fait la chose vraiment utile : demander à son renfort
(Claude/Gemini, un bon raisonneur) de réfléchir TOUR À TOUR sous plusieurs angles, de
FAIRE RESSORTIR LES CONFLITS (ex. : verrouiller des volets motorisés est inutile si le
courant peut tomber et les bloquer), puis de synthétiser un plan PRIORISÉ.

Deux garde-fous non négociables :
- C'est une PROPOSITION à valider. Jarvis n'exécute rien tout seul : chaque action
  sensible (volets, serrures, chauffage) passe par ta confirmation habituelle.
- Jamais « infaillible » : le plan affiche ses hypothèses et ses risques résiduels.
"""

from __future__ import annotations

PROMPT = """Tu prépares un plan pour : « {objectif} ».

Raisonne tour à tour sous plusieurs angles — énergie et chauffage, sécurité, eau et \
vivres, communications, santé et confort — et fais-les se CONTREDIRE là où c'est \
pertinent (par exemple : verrouiller des volets motorisés est inutile, voire nuisible, \
si le courant peut tomber et les bloquer ; chauffer à fond avant une coupure vide les \
réserves). Confronte les options au lieu de les empiler.

Puis synthétise un plan PRIORISÉ et concret, en français, structuré par domaine, avec \
pour chaque point l'action et sa raison en une ligne.

Règles impératives :
- Énonce explicitement tes HYPOTHÈSES et les RISQUES résiduels.
- Ne prétends JAMAIS que le plan est infaillible, parfait ou sans faille : signale ses limites.
- C'est une PROPOSITION à faire valider par le propriétaire. Chaque action sensible \
(volets, serrures, chauffage, portail) ne sera exécutée qu'après son accord explicite.
- Pour les informations, reste sur le légitime (météo, coupures réseau, routes). Aucun \
renseignement sur des personnes.

Termine par « À confirmer en priorité : » suivi de 3 à 5 actions clés."""


def build_planner_tools(renfort) -> list:
    """renfort : un objet avec .available (bool) et .ask(question, contexte) -> str."""
    from tools import Tool

    ask = getattr(renfort, "ask", None)
    if not (callable(ask) and getattr(renfort, "available", False)):
        return []   # sans renfort capable, pas de planificateur (le petit modèle local ne suffit pas)

    def preparer(objectif: str, contexte: str = "") -> str:
        if not (objectif or "").strip():
            return "Dites-moi ce qu'il faut préparer (ex. « une tempête de 3 jours »)."
        plan = ask(PROMPT.format(objectif=objectif.strip()), contexte)
        return ("Voici un plan à valider, Monsieur (je n'exécute rien sans votre accord) :\n\n"
                + plan)

    return [Tool(
        name="preparer_la_maison",
        description=("Élabore un PLAN multi-angles pour une demande complexe de préparation "
                     "(tempête, canicule, longue absence, coupure annoncée…). Fait réfléchir le "
                     "renfort sous plusieurs angles, fait ressortir les conflits, et PROPOSE un "
                     "plan priorisé à valider. N'exécute rien tout seul."),
        parameters={"type": "object",
                    "properties": {
                        "objectif": {"type": "string",
                                     "description": "ce qu'il faut préparer, en clair"},
                        "contexte": {"type": "string",
                                     "description": "infos utiles (facultatif)"}},
                    "required": ["objectif"]},
        run=preparer,
    )]
