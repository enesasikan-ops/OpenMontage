"""Renfort Claude : Jarvis (le modèle local) m'appelle pour les questions difficiles."""

import os

import anthropic

import config

SYSTEM_PROMPT = f"""Tu es le renfort de Jarvis, l'assistant vocal personnel de {config.USER_NAME}.
Jarvis (un petit modèle local) te transmet les questions trop difficiles pour lui.
Ta réponse sera LUE À VOIX HAUTE par Jarvis :
- réponds en français, de façon directe et naturelle, comme à l'oral ;
- pas de Markdown, pas de tableaux, pas de listes à puces, pas d'emojis ;
- vise 2 à 6 phrases, sauf si on te demande explicitement un texte long
  (un mail, un document) : dans ce cas, donne le texte complet.
"""


class ClaudeBridge:
    def __init__(self, client: "anthropic.Anthropic | None" = None):
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def ask(self, question: str, context: str = "") -> str:
        if not self.available:
            return ("Claude n'est pas configuré : il manque la clé ANTHROPIC_API_KEY "
                    "dans le fichier .env. Je réponds avec mes propres moyens.")

        content = question if not context else f"Contexte : {context}\n\nQuestion : {question}"
        try:
            response = self._get_client().beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                output_config={"effort": config.CLAUDE_EFFORT},
                # Si Claude refuse pour raison de sécurité, l'API réessaie
                # automatiquement avec un autre modèle adapté.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError:
            return "Ma clé Claude est refusée. Vérifie ANTHROPIC_API_KEY dans le fichier .env."
        except anthropic.RateLimitError:
            return "Claude est surchargé pour le moment. Réessaie dans une minute."
        except anthropic.APIStatusError as exc:
            return f"Claude a renvoyé une erreur ({exc.status_code}). Réessaie plus tard."
        except anthropic.APIConnectionError:
            return "Je n'arrive pas à joindre Claude. Vérifie la connexion internet."

        if response.stop_reason == "refusal":
            return "Claude a préféré ne pas répondre à cette question."

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text or "Claude n'a rien répondu."
