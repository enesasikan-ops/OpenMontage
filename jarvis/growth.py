"""Le journal des améliorations de Jarvis — comment il progresse, de façon encadrée.

Principe (amélioration continue, mais sûre) :
1. Quand Jarvis ne sait pas faire quelque chose, il l'écrit ici (outil noter_a_ameliorer).
2. Plus tard, Claude (le mentor) lit ce journal et écrit la nouvelle capacité, AVEC des tests.
3. L'utilisateur relit et valide avant que ça entre dans Jarvis.
4. Jarvis sait alors faire la nouvelle chose : ce qui était impossible devient possible.

Jarvis ne réécrit JAMAIS son propre code tout seul : chaque amélioration passe par des
tests et par ton accord. Ce fichier est la liste de souhaits, pas un exécuteur.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import config


class GrowthJournal:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            self.data = {"idees": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, idee: str, origine: str = "manuel") -> str:
        idee = idee.strip()
        if not idee:
            return "Il me faut une idée à noter."
        now = datetime.now(ZoneInfo(config.TIMEZONE))
        for e in self.data["idees"]:
            if e["idee"].lower() == idee.lower() and not e.get("fait"):
                e["compteur"] = e.get("compteur", 1) + 1  # déjà demandé : on compte
                self._save()
                return "C'était déjà dans ma liste d'améliorations, je note que ça revient."
        self.data["idees"].append({"idee": idee, "origine": origine, "fait": False,
                                   "compteur": 1, "date": now.date().isoformat()})
        self._save()
        return f"C'est noté dans ma liste d'améliorations : {idee}. On pourra l'ajouter plus tard."

    def pending(self) -> list[dict]:
        # Les plus redemandées d'abord.
        return sorted((e for e in self.data["idees"] if not e.get("fait")),
                      key=lambda e: e.get("compteur", 1), reverse=True)

    def mark_done(self, idee: str) -> bool:
        for e in self.data["idees"]:
            if e["idee"].lower() == idee.strip().lower():
                e["fait"] = True
                self._save()
                return True
        return False

    def text(self) -> str:
        pend = self.pending()
        if not pend:
            return "Ma liste d'améliorations est vide pour l'instant."
        lignes = []
        for e in pend:
            fois = f" (demandé {e['compteur']} fois)" if e.get("compteur", 1) > 1 else ""
            lignes.append(f"- {e['idee']}{fois}")
        return "Idées d'amélioration en attente :\n" + "\n".join(lignes)


# Fichiers sensibles que l'auto-amélioration ne doit JAMAIS modifier (sécurité en dur).
PROTECTED = ("config.py", "claude_bridge.py", "drone.py", "security.py", "brain.py",
             "main.py", "telegram_bot.py", "tools.py", ".env")

# Consigne donnée au mentor (Claude Code) pour qu'il code une amélioration en autonomie,
# mais sans jamais toucher au cœur sensible ni retirer les confirmations.
SELF_IMPROVE_POLICY = """Tu ajoutes une NOUVELLE capacité à Jarvis, en autonomie, dans l'atelier.
Règles de sécurité STRICTES (non négociables) :
- Crée un NOUVEAU fichier pour la capacité (ex. atelier/<nom>.py) et SES TESTS (pytest).
- Ne modifie AUCUN de ces fichiers du cœur : """ + ", ".join(PROTECTED) + """.
- Ne retire, n'affaiblis ni ne contournes JAMAIS une confirmation : toute action qui
  envoie, supprime, pilote, paie ou ouvre quelque chose doit demander confirmation.
- N'ajoute pas d'accès réseau caché, pas de collecte de données, rien qui sorte en douce.
- Écris des tests qui prouvent que ça marche, lance-les, et ne considère la tâche finie
  que si les tests passent.
- Termine par un résumé court en français : ce que tu as créé, où, et le résultat des tests.
Jarvis n'intègre rien tout seul : l'utilisateur relira et validera avant activation."""


def build_growth_tools(journal: GrowthJournal, agent=None) -> list:
    from tools import Tool

    s = {"type": "string"}

    def obj(props, required):
        return {"type": "object", "properties": props, "required": required}

    tools = [
        Tool(name="noter_a_ameliorer",
             description=("Note une capacité qui manque à Jarvis, pour l'ajouter plus tard. "
                          "À utiliser quand tu ne sais pas faire quelque chose, ou quand "
                          "l'utilisateur dit « tu devrais pouvoir... », « ce serait bien que tu saches... »."),
             parameters=obj({"idee": {**s, "description": "La capacité manquante, en une phrase."}}, ["idee"]),
             run=lambda idee: journal.add(idee, origine="jarvis")),
        Tool(name="journal_ameliorations",
             description="Liste les améliorations en attente (ce que Jarvis ne sait pas encore faire).",
             parameters=obj({}, []),
             run=lambda: journal.text()),
    ]

    if agent is not None:
        def ameliorer(idee: str = "") -> str:
            idee = idee.strip()
            if not idee:
                pend = journal.pending()
                if not pend:
                    return "Ma liste d'améliorations est vide, il n'y a rien à ajouter."
                idee = pend[0]["idee"]
            task = (f"{SELF_IMPROVE_POLICY}\n\nLa capacité à ajouter : {idee}")
            return agent.delegate(task)

        tools.append(Tool(
            name="ameliorer_jarvis",
            description=("Demande au mentor (Claude) d'ÉCRIRE une nouvelle capacité de Jarvis en "
                         "autonomie, avec ses tests, dans l'atelier. Prend l'idée donnée, ou la plus "
                         "demandée du journal. Le code n'est PAS activé : tu le relis et valides après."),
            parameters=obj({"idee": {**s, "description": "La capacité à coder (vide = la plus demandée)."}}, []),
            run=ameliorer,
            confirm=lambda idee="": ("Je vais demander à Claude d'écrire cette capacité (code + tests) "
                                     "dans l'atelier, sans toucher au cœur de Jarvis. On la validera avant "
                                     "de l'activer. OK ?")))
    return tools
