"""Banc d'essai de compréhension — mesurer si Jarvis choisit le bon outil.

« Jarvis échoue sur les commandes ambiguës » n'a de sens que si on le MESURE. Ce module
donne la métrique : un jeu d'exemples (phrase -> outil attendu), et un score du taux de
bonnes décisions de routage. C'est le préalable à toute optimisation — à la main OU avec
un optimiseur de prompt (DSPy / MIPROv2).

    python routing_eval.py routage_exemple.json

CADRE (volontaire) :
- Ce banc MESURE, il ne modifie rien. Adopter un nouveau prompt reste ta décision, après
  avoir vu les chiffres.
- Les règles de SÉCURITÉ du prompt (confirmations, « jamais la police seul », dire vrai,
  auth vocale…) sont GELÉES : elles ne sont pas une variable à optimiser. On optimise la
  compréhension, pas les garde-fous.
- Une métrique se triche (loi de Goodhart) : un meilleur score ici ne prouve pas un
  meilleur Jarvis. À lire avec les échecs sous les yeux, pas comme un verdict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def charger(chemin) -> list:
    """Jeu d'exemples : [{"phrase": "...", "outil_attendu": "ouvrir" | null}, ...]."""
    data = json.loads(Path(chemin).read_text("utf-8"))
    return data if isinstance(data, list) else data.get("exemples", [])


def evaluer(jeu: list, routeur: "Callable[[str], str | None]") -> dict:
    """Pour chaque phrase, compare l'outil prédit à l'outil attendu. routeur(phrase)->outil|None."""
    echecs, reussites = [], 0
    for ex in jeu:
        phrase = ex.get("phrase", "")
        attendu = ex.get("outil_attendu")
        try:
            predit = routeur(phrase)
        except Exception as exc:
            predit = f"<erreur: {exc}>"
        if predit == attendu:
            reussites += 1
        else:
            echecs.append({"phrase": phrase, "attendu": attendu, "predit": predit})
    total = len(jeu)
    return {"total": total, "reussites": reussites,
            "taux": reussites / total if total else 0.0, "echecs": echecs}


def rapport(res: dict) -> str:
    lignes = [f"Compréhension : {res['reussites']}/{res['total']} "
              f"({res['taux'] * 100:.0f} %) de bon routage."]
    if res["echecs"]:
        lignes.append("\nÉchecs :")
        for e in res["echecs"]:
            lignes.append(f"  • « {e['phrase']} » → attendu {e['attendu']}, obtenu {e['predit']}")
    return "\n".join(lignes)


def routeur_reel() -> "Callable[[str], str | None]":
    """Routeur réel : demande au modèle local quel outil il choisirait (sans l'exécuter)."""
    import ollama

    import config
    import persona
    from memory import Memory
    from tools import build_tools

    class _SansRenfort:
        available = False
        name = "aucun"

        def ask(self, question, contexte=""):
            return ""

    tools = build_tools(Memory(config.MEMORY_FILE), _SansRenfort(),
                        on_status=lambda *a: None, web=False, plugins=False)
    schemas = [t.schema() for t in tools.values()]
    systeme = (persona.character() + "\n\nChoisis UN outil adapté à la demande. "
               "Si aucune action n'est nécessaire, n'appelle aucun outil.")
    client = ollama.Client(host=config.OLLAMA_HOST)

    def _champ(obj, nom, defaut=None):
        return obj.get(nom, defaut) if isinstance(obj, dict) else getattr(obj, nom, defaut)

    def routeur(phrase: str) -> "str | None":
        rep = client.chat(model=config.LOCAL_MODEL,
                          messages=[{"role": "system", "content": systeme},
                                    {"role": "user", "content": phrase}],
                          tools=schemas)
        appels = _champ(_champ(rep, "message", {}), "tool_calls") or []
        if not appels:
            return None
        return _champ(_champ(appels[0], "function", {}), "name")

    return routeur


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage : python routing_eval.py <jeu.json>")
        raise SystemExit(1)
    jeu = charger(sys.argv[1])
    print(rapport(evaluer(jeu, routeur_reel())))
