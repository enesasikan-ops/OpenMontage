"""Les outils de Jarvis.

Chaque outil peut exiger une confirmation : Jarvis décrit alors ce qu'il va
faire et attend un « oui » avant d'agir. C'est le garde-fou sur les ACTIONS
(envoyer, supprimer, payer, ouvrir...), la conversation, elle, reste libre.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import config
from claude_bridge import ClaudeBridge
from memory import Memory

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str]
    # Si défini : phrase décrivant l'action, lue à l'utilisateur pour confirmation.
    confirm: Callable[..., str] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _now_text() -> str:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    return (f"Nous sommes le {JOURS[now.weekday()]} {now.day} {MOIS[now.month - 1]} "
            f"{now.year}, il est {now.hour}h{now.minute:02d}.")


def build_tools(memory: Memory, claude: ClaudeBridge,
                on_status: Callable[[str], None], reminders=None, lists=None) -> dict[str, Tool]:
    """reminders / lists : stockages des compétences (skills.py). Sans eux, outils de base seuls."""
    def ask_claude(question: str, contexte: str = "") -> str:
        on_status("Laisse-moi vérifier, je demande à Claude.")
        return claude.ask(question, contexte)

    tools = [
        Tool(
            name="heure_et_date",
            description="Donne la date et l'heure actuelles.",
            parameters={"type": "object", "properties": {}, "required": []},
            run=lambda: _now_text(),
        ),
        Tool(
            name="retenir",
            description=("Mémorise durablement un fait sur l'utilisateur ou ses projets "
                         "(préférence, info personnelle, rappel). À utiliser quand "
                         "l'utilisateur dit « retiens que... » ou partage une info utile."),
            parameters={
                "type": "object",
                "properties": {"fait": {"type": "string", "description": "Le fait à retenir, en une phrase."}},
                "required": ["fait"],
            },
            run=lambda fait: memory.remember(fait),
        ),
        Tool(
            name="oublier",
            description="Supprime de la mémoire les faits qui contiennent un mot-clé.",
            parameters={
                "type": "object",
                "properties": {"mot_cle": {"type": "string", "description": "Mot-clé des faits à oublier."}},
                "required": ["mot_cle"],
            },
            run=lambda mot_cle: memory.forget(mot_cle),
            confirm=lambda mot_cle: (
                f"Je vais oublier : {' ; '.join(memory.find(mot_cle)) or 'rien (aucun fait trouvé)'}."
            ),
        ),
        Tool(
            name="demander_a_claude",
            description=("Pose la question à Claude, une IA beaucoup plus puissante, via internet. "
                         "À utiliser pour : raisonnement complexe, maths, analyse, conseils "
                         "importants, rédaction (mail, document), code, sujets où tu n'es pas sûr, "
                         "ou quand l'utilisateur dit « demande à Claude ». Ne l'utilise PAS "
                         "pour les questions simples ou la conversation courante."),
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "La question complète, reformulée clairement."},
                    "contexte": {"type": "string", "description": "Infos utiles de la conversation (facultatif)."},
                },
                "required": ["question"],
            },
            run=ask_claude,
        ),
    ]
    if reminders is not None and lists is not None:
        from skills import build_skills  # import tardif : skills.py importe Tool d'ici

        tools += build_skills(reminders, lists)
    return {t.name: t for t in tools}
