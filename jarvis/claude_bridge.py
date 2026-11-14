"""Renfort Claude : Jarvis (le modèle local) m'appelle pour les questions difficiles.

Modes, choisis avec JARVIS_RENFORT dans le fichier .env :
- "abonnement" : passe par Claude Code installé sur le Mac, connecté à ton compte
                 Claude (ton abonnement, pas de coût en plus, usage personnel) ;
- "api"        : passe par l'API Anthropic avec ANTHROPIC_API_KEY (payé à l'usage) ;
- "gemini"     : passe par Gemini (Google) avec GEMINI_API_KEY (payé à l'usage) ;
- "gemini-abonnement" : passe par Gemini CLI, connecté à ton compte Google ;
- "aucun"      : pas de renfort, Jarvis reste 100 % local.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import anthropic

import config
import persona


def _designation() -> str:
    """Comment nommer le propriétaire VERS LE CLOUD : neutre si l'anonymisation est active."""
    return "son propriétaire" if getattr(config, "RENFORT_ANONYME", True) else config.USER_NAME


def _anonymiser(texte: str) -> str:
    """Retire les identifiants évidents (prénom, ville) d'un texte qui part au cloud.

    Point de contrôle UNIQUE de la vie privée côté renfort : tout ce qui sort par ask()
    passe ici. Ne prétend pas tout attraper (le modèle local peut glisser une autre PII),
    mais supprime les fuites systématiques du prénom et de la ville.
    """
    if not texte or not getattr(config, "RENFORT_ANONYME", True):
        return texte
    out = texte
    nom = (config.USER_NAME or "").strip()
    if len(nom) >= 2:
        out = re.sub(rf"\b{re.escape(nom)}\b", "mon propriétaire", out, flags=re.IGNORECASE)
    ville = (getattr(config, "CITY", "") or "").strip()
    if len(ville) >= 2:
        out = re.sub(rf"\b{re.escape(ville)}\b", "ma région", out, flags=re.IGNORECASE)
    return out


# Les prompts partent au cloud : on les passe par _anonymiser pour qu'AUCUN identifiant
# (prénom via persona, ville…) ne s'y glisse, d'où qu'il vienne.
SYSTEM_PROMPT = _anonymiser(f"""Tu es le renfort de Jarvis, l'assistant vocal personnel de {_designation()}.
Jarvis (un petit modèle local) te transmet les questions trop difficiles pour lui.
Ta réponse sera LUE À VOIX HAUTE par Jarvis :
- réponds en français, de façon directe et naturelle, comme à l'oral ;
- {persona.claude_style()}
- pas de Markdown, pas de tableaux, pas de listes à puces, pas d'emojis ;
- vise 2 à 6 phrases, sauf si on te demande explicitement un texte long
  (un mail, un document) : dans ce cas, donne le texte complet.
""")

CLI_TIMEOUT_S = 180
AGENT_TIMEOUT_S = 900  # une tâche d'agent peut être longue

AGENT_PROMPT = _anonymiser(f"""Tu es le mentor de Jarvis, l'assistant personnel de {_designation()}.
Jarvis te confie une tâche importante (souvent du code ou une recherche approfondie)
parce qu'elle dépasse ses moyens. Tu travailles sur l'ordinateur de {_designation()},
uniquement dans le dossier de travail autorisé (l'atelier de Jarvis).
- Fais le travail de bout en bout, proprement.
- Ne touche à rien en dehors de l'atelier. Ne lance aucune commande destructrice.
- Termine par un résumé clair et court, en français, de ce que tu as fait et de
  l'endroit où se trouve le résultat. Ce résumé sera lu à voix haute par Jarvis.""")

Runner = Callable[..., subprocess.CompletedProcess]


def _format(question: str, context: str) -> str:
    question, context = _anonymiser(question), _anonymiser(context)
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


class GeminiCliBackend:
    """Renfort via Gemini CLI, connecté à ton compte Google (ton abonnement, pas de coût en plus)."""

    name = "Gemini (abonnement Google, Gemini CLI)"
    _instruction = "Réponds en français, directement et naturellement, en quelques phrases."

    def __init__(self, runner: Runner = subprocess.run, which: Callable = shutil.which):
        self._run = runner
        self._which = which

    @property
    def available(self) -> bool:
        return self._which("gemini") is not None

    def unavailable_reason(self) -> str:
        return ("Gemini CLI n'est pas installé (npm install -g @google/gemini-cli, "
                "puis lance « gemini » une fois pour te connecter à ton compte Google)")

    def command(self) -> list[str]:
        cmd = [
            self._which("gemini") or "gemini",
            "-p", self._instruction,          # déclenche le mode non-interactif
            "-o", "text",
            "--approval-mode", "plan",         # lecture seule : il répond, il n'agit pas
        ]
        if config.GEMINI_CLI_MODEL:
            cmd += ["-m", config.GEMINI_CLI_MODEL]
        return cmd

    def delegate(self, task: str) -> str:  # noqa: ARG002
        return ("Pour exécuter une vraie tâche sur l'ordinateur, Jarvis passe par Claude Code. "
                "Gemini sert ici à répondre, pas à agir.")

    def ask(self, question: str, context: str = "") -> str:
        env = dict(os.environ)
        # Sans ça, Gemini CLI utiliserait la clé API (payante) au lieu de l'abonnement.
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"):
            env.pop(key, None)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        prompt = f"{SYSTEM_PROMPT}\n\n{_format(question, context)}"
        try:
            result = self._run(
                self.command(), input=prompt, capture_output=True, text=True,
                timeout=CLI_TIMEOUT_S, cwd=str(config.DATA_DIR), env=env)
        except FileNotFoundError:
            return "Je ne trouve pas Gemini CLI sur cet ordinateur."
        except subprocess.TimeoutExpired:
            return "Gemini met trop de temps à répondre. Réessaie dans un instant."
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").lower()
            if any(w in err for w in ("login", "auth", "credential", "oauth", "sign in")):
                return "Gemini CLI n'est pas connecté. Lance « gemini » dans le Terminal et connecte-toi."
            if any(w in err for w in ("quota", "limit", "rate")):
                return "Ta limite Gemini est atteinte pour le moment."
            return "Gemini CLI a eu un problème. Réessaie plus tard."
        return result.stdout.strip() or "Gemini n'a rien répondu."


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

    def describe_image(self, image: bytes, question: str = "") -> str:
        """Décrit une image (ex. la vue du drone). Gemini lit nativement les images."""
        import base64
        import urllib.error

        q = _anonymiser(question or "Décris ce que tu vois sur cette image, en une ou deux phrases, en français.")
        body = {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(image).decode("ascii")}},
                {"text": q},
            ]}],
        }
        try:
            data = self._request(body)
        except urllib.error.HTTPError as exc:
            return "Ma clé Gemini est refusée." if exc.code in (400, 401, 403) else "Gemini a renvoyé une erreur."
        except (urllib.error.URLError, OSError):
            return "Je n'arrive pas à joindre Gemini pour analyser l'image."
        except (json.JSONDecodeError, ValueError):
            return "Gemini a renvoyé une réponse illisible."
        candidates = data.get("candidates") or []
        if not candidates:
            return "Gemini n'a rien dit sur l'image."
        parts = (candidates[0].get("content") or {}).get("parts") or []
        return "".join(pt.get("text", "") for pt in parts).strip() or "Gemini n'a rien dit sur l'image."

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


# --- Repli automatique : si un renfort ne peut pas coder, l'autre prend le relais --

# Messages d'ÉCHEC RÉEL d'un renfort (quota, non connecté, panne) : ils font passer
# au renfort suivant. Ce sont des phrases exactes renvoyées par les backends ci-dessus ;
# si on en change une, la mettre à jour ici aussi. Un « refus de sécurité » n'en fait
# PAS partie : on ne contourne jamais un refus en passant à l'autre renfort.
_ECHECS_EXACTS = frozenset({
    # Claude
    "Claude Code n'est pas connecté. Lance « claude » dans le Terminal et connecte-toi.",
    "Tu as atteint la limite de ton abonnement Claude pour le moment. Je réponds avec mes moyens.",
    "Claude Code a eu un problème. Réessaie plus tard.",
    "Je ne trouve pas Claude Code sur cet ordinateur.",
    "Claude met trop de temps à répondre. Réessaie dans un instant.",
    "La tâche a pris trop de temps, je l'ai arrêtée.",
    "Ma clé Claude est refusée. Vérifie ANTHROPIC_API_KEY dans le fichier .env.",
    "Claude est surchargé pour le moment. Réessaie dans une minute.",
    "Je n'arrive pas à joindre Claude. Vérifie la connexion internet.",
    # Gemini
    "Je ne trouve pas Gemini CLI sur cet ordinateur.",
    "Gemini met trop de temps à répondre. Réessaie dans un instant.",
    "Gemini CLI n'est pas connecté. Lance « gemini » dans le Terminal et connecte-toi.",
    "Ta limite Gemini est atteinte pour le moment.",
    "Gemini CLI a eu un problème. Réessaie plus tard.",
    "Ma clé Gemini est refusée. Vérifie GEMINI_API_KEY dans le fichier .env.",
    "Gemini est surchargé ou ta limite est atteinte. Réessaie plus tard.",
    "Je n'arrive pas à joindre Gemini. Vérifie la connexion internet.",
    "Gemini a renvoyé une réponse illisible.",
    "Gemini n'a rien répondu.",
})
_ECHECS_PREFIXES = ("Claude a renvoyé une erreur", "Gemini a renvoyé une erreur")

# « Je sais répondre mais pas agir sur la machine » (Gemini, ou Claude en mode API) :
# ce n'est pas un échec, c'est le signal qu'il faut passer par la proposition écrite.
_NE_SAIT_PAS_AGIR = "Pour exécuter une vraie tâche"

_RE_DOSSIER = re.compile(r"Dossier de travail à utiliser[^:]*:\s*(.+)")
_RE_ENTETE_FICHIER = r"(?im)^#{1,6}\s*fichier\s*:\s*(.+?)\s*$"


def _ne_sait_pas_agir(reponse: str) -> bool:
    """True si le renfort sait répondre mais pas piloter la machine (→ proposition écrite)."""
    return (reponse or "").strip().startswith(_NE_SAIT_PAS_AGIR)


def _renfort_a_echoue(reponse: str) -> bool:
    """True si la réponse est un échec réel de capacité (quota, non connecté, panne…)."""
    r = (reponse or "").strip()
    return r in _ECHECS_EXACTS or r.startswith(_ECHECS_PREFIXES)


def _extraire_fichiers(reponse: str) -> dict[str, str]:
    """Récupère les fichiers d'une réponse « ### fichier: nom » + bloc ``` ``` ```."""
    bouts = re.split(_RE_ENTETE_FICHIER, reponse)
    fichiers: dict[str, str] = {}
    for i in range(1, len(bouts), 2):
        nom = bouts[i].strip()
        corps = bouts[i + 1] if i + 1 < len(bouts) else ""
        bloc = re.search(r"```[a-zA-Z0-9_]*\s*\n(.*?)```", corps, re.DOTALL)
        contenu = (bloc.group(1) if bloc else corps).strip()
        if nom and contenu:
            fichiers[nom] = contenu
    return fichiers


def _ecrire_fichiers(folder: Path, fichiers: dict[str, str]) -> list[str]:
    """Écrit les fichiers dans le dossier, en refusant toute sortie du dossier (anti-traversée)."""
    base = folder.resolve()
    ecrits = []
    for nom, contenu in fichiers.items():
        cible = (base / nom).resolve()
        if base != cible and base not in cible.parents:  # jamais hors du dossier de travail
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(contenu.rstrip("\n") + "\n", encoding="utf-8")
        ecrits.append(nom)
    return ecrits


class MentorEnCascade:
    """Un renfort principal doublé d'un remplaçant. Peu importe lequel est devant :
    Claude ou Gemini peuvent jouer l'un ou l'autre rôle.

    Si le principal ne peut pas (absent, non connecté, quota épuisé, panne), le
    remplaçant prend le relais — pour répondre comme pour coder. Pour coder :
    - Claude Code agit directement dans l'atelier (il en a le droit) ;
    - les autres (Gemini, Claude en mode API) ne pilotent PAS la machine : ils
      PROPOSENT les fichiers (texte), et c'est ce module de confiance qui les écrit
      dans l'atelier.
    Dans tous les cas la suite est inchangée : sandbox + tes tests + ton ✅.
    """

    def __init__(self, principal, repli):
        self.principal = principal
        self.repli = repli

    @property
    def available(self) -> bool:
        return self.principal.available or self.repli.available

    @property
    def name(self) -> str:
        if self.principal.available:
            return f"{self.principal.name} (repli : {self.repli.name})"
        return self.repli.name

    def unavailable_reason(self) -> str:
        return f"{self.principal.unavailable_reason()} ; et {self.repli.unavailable_reason()}"

    def ask(self, question: str, context: str = "") -> str:
        reponse = None
        if self.principal.available:
            reponse = self.principal.ask(question, context)
            if not _renfort_a_echoue(reponse):
                return reponse
        if self.repli.available:
            return self.repli.ask(question, context)
        if reponse is not None:
            return reponse
        return f"Aucun renfort disponible : {self.unavailable_reason()}."

    def delegate(self, task: str) -> str:
        ok, resultat = self._coder(self.principal, task)
        if ok:
            return resultat
        if not self.repli.available:
            return resultat
        ok2, resultat2 = self._coder(self.repli, task)
        if ok2:
            return (f"{_nom(self.principal)} n'a pas pu coder cette fois, "
                    f"{_nom(self.repli)} a pris le relais. {resultat2}")
        return f"{resultat}\nEt le relais aussi : {resultat2}"

    def _coder(self, backend, task: str) -> "tuple[bool, str]":
        """Fait coder une amélioration par un renfort. (réussite, message)."""
        if not backend.available:
            return False, backend.unavailable_reason()
        resultat = backend.delegate(task)
        if not _renfort_a_echoue(resultat) and not _ne_sait_pas_agir(resultat):
            return True, resultat          # le renfort a agi lui-même (Claude Code)
        if _renfort_a_echoue(resultat):
            return False, resultat          # échec réel (quota, panne) → au suivant
        return self._proposer_et_ecrire(backend, task)  # « sait répondre, pas agir »

    def _proposer_et_ecrire(self, backend, task: str) -> "tuple[bool, str]":
        """Le renfort PROPOSE le code (texte) ; on écrit les fichiers dans l'atelier."""
        dossier = _RE_DOSSIER.search(task)
        if not dossier:
            return True, backend.ask(task)  # tâche libre (mentor) : une réponse suffit
        folder = Path(dossier.group(1).strip())
        consigne = (
            task + "\n\nDonne CHAQUE fichier sous cette forme exacte, et rien d'autre :\n"
            "### fichier: nom_du_fichier.py\n```python\n<contenu complet du fichier>\n```"
        )
        reponse = backend.ask(consigne)
        if _renfort_a_echoue(reponse):
            return False, reponse
        fichiers = _extraire_fichiers(reponse)
        if not fichiers:
            return False, "pas de fichiers exploitables dans la réponse"
        ecrits = _ecrire_fichiers(folder, fichiers)
        return True, f"Fichiers proposés : {', '.join(ecrits)}."


def _nom(backend) -> str:
    return getattr(backend, "name", "un renfort")


def _choisir_repli(principal):
    """Choisit le remplaçant. 'auto' = l'autre famille que le principal (Claude ↔ Gemini).
    Un remplaçant n'est retenu que s'il est réellement disponible."""
    if config.OFFLINE:
        return None
    choix = config.RENFORT_REPLI
    if choix == "aucun":
        return None
    principal_est_claude = isinstance(principal, (SubscriptionBackend, ApiBackend))

    def _dispo(backend):
        return backend if backend is not None and backend.available else None

    # Choix explicite d'un remplaçant.
    if choix in ("gemini-cli", "gemini-abonnement"):
        return _dispo(GeminiCliBackend()) if principal_est_claude else None
    if choix == "gemini":
        return _dispo(GeminiBackend()) if principal_est_claude else None
    if choix in ("claude", "abonnement"):
        return None if principal_est_claude else _dispo(SubscriptionBackend())
    if choix in ("claude-api", "api"):
        return None if principal_est_claude else _dispo(ApiBackend())
    if choix != "auto":
        return None

    # auto : le principal est Claude → repli Gemini ; le principal est Gemini → repli Claude.
    if principal_est_claude:
        if config.GEMINI_CLI_ENABLE:
            return _dispo(GeminiCliBackend())
        if config.GEMINI_KEY:
            return _dispo(GeminiBackend())
        return None
    return _dispo(SubscriptionBackend()) or _dispo(ApiBackend())


class ClaudeBridge:
    def __init__(self, backend=None):
        self.backend = backend or self._from_config()

    @staticmethod
    def _principal():
        mode = config.RENFORT
        if mode == "api":
            return ApiBackend()
        if mode == "gemini":
            return GeminiBackend()
        if mode in ("gemini-abonnement", "gemini-cli"):
            return GeminiCliBackend()
        if mode == "aucun":
            return NoBackend()
        return SubscriptionBackend()

    @staticmethod
    def _from_config():
        principal = ClaudeBridge._principal()
        repli = _choisir_repli(principal)
        return MentorEnCascade(principal, repli) if repli is not None else principal

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
