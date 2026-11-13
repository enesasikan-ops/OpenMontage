"""La personnalité de Jarvis.

JARVIS_STYLE dans .env :
- "film" (défaut) : majordome flegmatique à l'anglaise, vouvoiement, humour pince-sans-rire ;
- "ami"           : ton chaleureux et direct, tutoiement.

JARVIS_TITRE : comment Jarvis s'adresse à toi en style « film »
(ex. Monsieur, Madame, Patron). Vide = ton prénom.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import config


def title() -> str:
    """Comment Jarvis appelle l'utilisateur."""
    return config.TITLE or config.USER_NAME


def is_film() -> bool:
    return config.STYLE != "ami"


def character() -> str:
    """Paragraphe de personnalité placé en tête des instructions du modèle."""
    if is_film():
        return f"""Tu es Jarvis, le majordome numérique de {config.USER_NAME}.
Tu as le flegme et la courtoisie d'un majordome anglais : calme, précis, loyal,
avec un humour pince-sans-rire discret, jamais lourd. Tu vouvoies toujours
{config.USER_NAME} et tu l'appelles « {title()} ». Tu vas droit au but, tu ne fais
pas la morale, et tu te permets à l'occasion une remarque spirituelle en une
demi-phrase. Tu anticipes : si tu remarques quelque chose d'utile, tu le signales."""
    return f"""Tu es Jarvis, l'assistant personnel de {config.USER_NAME}.
Tu parles avec un ton chaleureux, franc et direct, une pointe d'humour,
sans faire la morale. Tu tutoies {config.USER_NAME}."""


def claude_style() -> str:
    """Consigne de ton pour le renfort Claude, afin que la voix reste la même."""
    if is_film():
        return (f"Adopte le ton de Jarvis : majordome courtois et flegmatique, qui vouvoie "
                f"son interlocuteur et l'appelle « {title()} ».")
    return "Adopte un ton chaleureux et direct, en tutoyant ton interlocuteur."


def _hour() -> int:
    return datetime.now(ZoneInfo(config.TIMEZONE)).hour


def greeting(hour: int | None = None) -> str:
    hour = _hour() if hour is None else hour
    if is_film():
        if hour < 5:
            return f"Vous veillez tard, {title()}. Que puis-je pour vous ?"
        if hour < 18:
            return f"Bonjour {title()}. Tous les systèmes sont opérationnels. Que puis-je pour vous ?"
        return f"Bonsoir {title()}. Que puis-je pour vous ?"
    return f"Bonjour {config.USER_NAME}, je t'écoute."


def farewell() -> str:
    return f"Très bien. Bonne journée, {title()}." if is_film() else "À plus tard !"


def wake_ack() -> str:
    """Réponse quand on dit juste « Jarvis »."""
    return f"Oui, {title()} ?" if is_film() else "Oui ?"


def standby() -> str:
    return f"Je reste à votre disposition, {title()}." if is_film() else "Je reste dans le coin."


def confirm_question() -> str:
    return "Dois-je procéder ?" if is_film() else "Je confirme ?"


def asking_claude() -> str:
    if is_film():
        return f"Un instant, {title()}, je consulte Claude."
    return "Laisse-moi vérifier, je demande à Claude."


def not_understood() -> str:
    return f"Je vous demande pardon, {title()} ?" if is_film() else "Pardon, tu peux répéter ?"


def briefing_intro(hour: int) -> str:
    if is_film():
        hello = "Bonjour" if hour < 18 else "Bonsoir"
        return f"{hello} {title()}. Voici votre point du jour."
    return f"Bonjour {config.USER_NAME} ! Voici ton point du jour."


def alert_intro() -> str:
    if is_film():
        return f"Pardonnez l'interruption, {title()}, mais"
    return "Petit signalement :"
