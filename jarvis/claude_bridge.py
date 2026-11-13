"""Renfort Claude : Jarvis (le modèle local) m'appelle pour les questions difficiles.

Trois modes, choisis avec JARVIS_RENFORT dans le fichier .env :
- "abonnement" : passe par Claude Code installé sur le Mac, connecté à ton compte
                 Claude (ton abonnement, pas de coût en plus, usage personnel) ;
- "api"        : passe par l'API Anthropic avec ANTHROPIC_API_KEY (payé à l'usage) ;
- "aucun"      : pas de renfort, Jarvis reste 100 % local.
"""

import os
import shutil
import subprocess
from typing import Callable

import anthropic

import config
import persona

SYSTEM_PROMPT = f"""Tu es le renfort de Jarvis, l'assistant vocal personnel de {config.USER_NAME}.
Jarvis (un petit modèle local) te transmet les questions trop difficiles pour lui.
Ta réponse sera LUE À VOIX HAUTE par Jarvis :
- réponds en français, de façon directe et naturelle, comme à l'oral ;
- {persona.claude_style()}
- pas de Markdown, pas de tableaux, pas de listes à puces, pas d'emojis ;
- vise 2 à 6 phrases, sauf si on te demande explicitement un texte long
  (un mail, un document) : dans ce cas, donne le texte complet.
"""

CLI_TIMEOUT_S = 180

Runner = Callable[..., subprocess.CompletedProcess]


def _format(question: str, context: str) -> str:
    return question if not context else f"Contexte : {context}\n\nQuestion : {question}"


class ApiBackend:
    """Renfort via l'API Anthropic (clé ANTHROPIC_API_KEY, paiement à l'usage)."""

    name = "Claude via l'API"

    def __init__(self, client: "anthropic.Anthropic | None" = None):
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))

    def unavailable_reason(self) -> str:
        return "il manque la clé ANTHROPIC_API_KEY dans le fichier .env"

    def ask(self, question: str, context: str = "") -> str:
        if self._client is None:
            self._client = anthropic.Anthropic()
        try:
            response = self._client.beta.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                output_config={"effort": config.CLAUDE_EFFORT},
                # Si Claude refuse pour raison de sécurité, l'API réessaie
                # automatiquement avec un autre modèle adapté.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                messages=[{"role": "user", "content": _format(question, context)}],
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


class SubscriptionBackend:
    """Renfort via Claude Code (`claude -p`), connecté à ton abonnement Claude."""

    name = "Claude via ton abonnement (Claude Code)"

    def __init__(self, runner: Runner = subprocess.run, which: Callable = shutil.which):
        self._run = runner
        self._which = which

    @property
    def available(self) -> bool:
        return self._which("claude") is not None

    def unavailable_reason(self) -> str:
        return ("Claude Code n'est pas installé sur cet ordinateur "
                "(brew install --cask claude-code, puis lance « claude » une fois pour te connecter)")

    def command(self) -> list[str]:
        # Chemin complet : sous Windows, « claude » peut être un claude.cmd
        # que Python ne sait pas lancer par son seul nom.
        cmd = [
            self._which("claude") or "claude", "-p",
            "--output-format", "text",
            "--system-prompt", SYSTEM_PROMPT,
            "--tools", "",               # aucun outil : Claude répond, il n'agit pas
            "--strict-mcp-config",       # aucun connecteur
            "--setting-sources", "user",  # ignore les réglages des projets
            "--no-session-persistence",  # ne garde pas la conversation
        ]
        if config.CLAUDE_CLI_MODEL:
            cmd += ["--model", config.CLAUDE_CLI_MODEL]
        return cmd

    def ask(self, question: str, context: str = "") -> str:
        env = dict(os.environ)
        # Sans ça, Claude Code utiliserait la clé API (payante) au lieu de l'abonnement.
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            result = self._run(
                self.command(),
                input=_format(question, context),  # par l'entrée standard : rien dans la liste des processus
                capture_output=True, text=True, timeout=CLI_TIMEOUT_S,
                cwd=str(config.DATA_DIR),          # dossier neutre : pas de CLAUDE.md de projet
                env=env,
            )
        except FileNotFoundError:
            return "Je ne trouve pas Claude Code sur cet ordinateur."
        except subprocess.TimeoutExpired:
            return "Claude met trop de temps à répondre. Réessaie dans un instant."

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").lower()
            if any(w in err for w in ("login", "log in", "auth", "/login")):
                return "Claude Code n'est pas connecté. Lance « claude » dans le Terminal et connecte-toi."
            if any(w in err for w in ("limit", "quota", "usage")):
                return "Tu as atteint la limite de ton abonnement Claude pour le moment. Je réponds avec mes moyens."
            return "Claude Code a eu un problème. Réessaie plus tard."
        return result.stdout.strip() or "Claude n'a rien répondu."


class NoBackend:
    name = "aucun renfort (100 % local)"
    available = False

    def unavailable_reason(self) -> str:
        return "le renfort Claude est désactivé (mode 100 % local)"

    def ask(self, question: str, context: str = "") -> str:  # noqa: ARG002
        return ""


class ClaudeBridge:
    def __init__(self, backend=None):
        self.backend = backend or self._from_config()

    @staticmethod
    def _from_config():
        mode = config.RENFORT
        if mode == "api":
            return ApiBackend()
        if mode == "aucun":
            return NoBackend()
        return SubscriptionBackend()

    @property
    def available(self) -> bool:
        return self.backend.available

    @property
    def name(self) -> str:
        return self.backend.name

    def ask(self, question: str, context: str = "") -> str:
        if not self.backend.available:
            return (f"Je ne peux pas demander à Claude : {self.backend.unavailable_reason()}. "
                    "Je réponds avec mes propres moyens.")
        return self.backend.ask(question, context)
