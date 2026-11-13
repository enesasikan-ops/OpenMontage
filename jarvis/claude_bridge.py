"""Renfort Claude : Jarvis (le modèle local) m'appelle pour les questions difficiles.

Modes, choisis avec JARVIS_RENFORT dans le fichier .env :
- "abonnement" : passe par Claude Code installé sur le Mac, connecté à ton compte
                 Claude (ton abonnement, pas de coût en plus, usage personnel) ;
- "api"        : passe par l'API Anthropic avec ANTHROPIC_API_KEY (payé à l'usage) ;
- "gemini"     : passe par Gemini (Google) avec GEMINI_API_KEY (payé à l'usage) ;
- "aucun"      : pas de renfort, Jarvis reste 100 % local.
"""

import json
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
AGENT_TIMEOUT_S = 900  # une tâche d'agent peut être longue

AGENT_PROMPT = f"""Tu es le mentor de Jarvis, l'assistant personnel de {config.USER_NAME}.
Jarvis te confie une tâche importante (souvent du code ou une recherche approfondie)
parce qu'elle dépasse ses moyens. Tu travailles sur l'ordinateur de {config.USER_NAME},
uniquement dans le dossier de travail autorisé (l'atelier de Jarvis).
- Fais le travail de bout en bout, proprement.
- Ne touche à rien en dehors de l'atelier. Ne lance aucune commande destructrice.
- Termine par un résumé clair et court, en français, de ce que tu as fait et de
  l'endroit où se trouve le résultat. Ce résumé sera lu à voix haute par Jarvis."""

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

    def delegate(self, task: str) -> str:  # noqa: ARG002
        return ("Pour exécuter une vraie tâche sur l'ordinateur, il me faut Claude Code "
                "(mode abonnement), pas la clé API. Installe-le pour activer ce mode.")

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

        return self._read_result(result)

    @staticmethod
    def _read_result(result) -> str:
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").lower()
            if any(w in err for w in ("login", "log in", "auth", "/login")):
                return "Claude Code n'est pas connecté. Lance « claude » dans le Terminal et connecte-toi."
            if any(w in err for w in ("limit", "quota", "usage")):
                return "Tu as atteint la limite de ton abonnement Claude pour le moment. Je réponds avec mes moyens."
            return "Claude Code a eu un problème. Réessaie plus tard."
        return result.stdout.strip() or "Claude n'a rien répondu."

    # --- Mode « mentor » : Claude exécute une tâche en agent sur le PC ---------

    def agent_command(self) -> list[str]:
        """Claude Code avec de vrais outils, confiné à l'atelier de Jarvis."""
        cmd = [
            self._which("claude") or "claude", "-p",
            "--output-format", "text",
            "--system-prompt", AGENT_PROMPT,
            "--add-dir", str(config.WORKSPACE),   # ne travaille que dans l'atelier
            "--allowedTools", "Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch",
            "--permission-mode", "acceptEdits",
            "--max-turns", str(config.AGENT_MAX_TURNS),
            "--strict-mcp-config",
            "--setting-sources", "user",
            "--no-session-persistence",
        ]
        if config.CLAUDE_CLI_MODEL:
            cmd += ["--model", config.CLAUDE_CLI_MODEL]
        return cmd

    def delegate(self, task: str) -> str:
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        config.WORKSPACE.mkdir(parents=True, exist_ok=True)
        try:
            result = self._run(
                self.agent_command(), input=task, capture_output=True, text=True,
                timeout=AGENT_TIMEOUT_S, cwd=str(config.WORKSPACE), env=env)
        except FileNotFoundError:
            return "Je ne trouve pas Claude Code sur cet ordinateur."
        except subprocess.TimeoutExpired:
            return "La tâche a pris trop de temps, je l'ai arrêtée."
        return self._read_result(result)


class GeminiBackend:
    """Renfort via Gemini, l'IA de Google (clé API Google AI Studio, payé à l'usage)."""

    name = "Gemini (Google)"
    _endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, request: Callable | None = None):
        self._request = request or self._http

    @property
    def available(self) -> bool:
        return bool(config.GEMINI_KEY)

    def unavailable_reason(self) -> str:
        return ("il manque la clé GEMINI_API_KEY dans le fichier .env "
                "(à créer sur aistudio.google.com)")

    def _http(self, body: dict) -> dict:
        import urllib.request

        url = self._endpoint.format(model=config.GEMINI_MODEL)
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": config.GEMINI_KEY})
        with urllib.request.urlopen(req, timeout=CLI_TIMEOUT_S) as response:  # noqa: S310 (URL fixe, https)
            return json.loads(response.read().decode("utf-8"))

    def delegate(self, task: str) -> str:  # noqa: ARG002
        return ("Pour exécuter une vraie tâche sur l'ordinateur, il me faut Claude Code "
                "(mode abonnement). Gemini ne peut que répondre, pas agir sur la machine.")

    def ask(self, question: str, context: str = "") -> str:
        import urllib.error

        body = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": _format(question, context)}]}],
        }
        try:
            data = self._request(body)
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403):
                return "Ma clé Gemini est refusée. Vérifie GEMINI_API_KEY dans le fichier .env."
            if exc.code == 429:
                return "Gemini est surchargé ou ta limite est atteinte. Réessaie plus tard."
            return f"Gemini a renvoyé une erreur ({exc.code}). Réessaie plus tard."
        except (urllib.error.URLError, OSError):
            return "Je n'arrive pas à joindre Gemini. Vérifie la connexion internet."
        except (json.JSONDecodeError, ValueError):
            return "Gemini a renvoyé une réponse illisible."

        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason")
            return "Gemini a préféré ne pas répondre." if reason else "Gemini n'a rien répondu."
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or "Gemini n'a rien répondu."


class NoBackend:
    name = "aucun renfort (100 % local)"
    available = False

    def unavailable_reason(self) -> str:
        return "le renfort Claude est désactivé (mode 100 % local)"

    def ask(self, question: str, context: str = "") -> str:  # noqa: ARG002
        return ""

    def delegate(self, task: str) -> str:  # noqa: ARG002
        return "Le mode mentor est désactivé (pas de renfort Claude)."


class ClaudeBridge:
    def __init__(self, backend=None):
        self.backend = backend or self._from_config()

    @staticmethod
    def _from_config():
        mode = config.RENFORT
        if mode == "api":
            return ApiBackend()
        if mode == "gemini":
            return GeminiBackend()
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

    def delegate(self, task: str) -> str:
        if not self.backend.available:
            return (f"Je ne peux pas confier cette tâche à Claude : "
                    f"{self.backend.unavailable_reason()}.")
        return self.backend.delegate(task)
