"""Jarvis sur Telegram : écris-lui ou envoie-lui un vocal depuis ton téléphone.

    python telegram_bot.py

Sécurité : le bot ne répond qu'à TON compte Telegram (JARVIS_TELEGRAM_ID).
Toute autre personne qui le trouverait reçoit un refus poli.
"""

import asyncio
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from main import check_ollama  # charge aussi le fichier .env

import config  # noqa: E402
import persona  # noqa: E402
from brain import Brain  # noqa: E402
from claude_bridge import ClaudeBridge, GeminiBackend, GeminiCliBackend  # noqa: E402
from memory import Memory  # noqa: E402
from proactive import Proactive  # noqa: E402
from security import Sentinel  # noqa: E402
from smarthome import SmartHome  # noqa: E402
from skills import Lists, Reminders, ReminderWatcher  # noqa: E402
from tools import build_tools  # noqa: E402

log = logging.getLogger("jarvis.telegram")

CONFIRM_TIMEOUT_S = 120
TELEGRAM_MAX_LEN = 4000


class TelegramJarvis:
    def __init__(self, brain_factory, allowed_id: int | None, listener=None, speaker=None):
        """brain_factory(confirm, on_status) -> Brain ; listener/speaker : voix (facultatifs)."""
        self.allowed_id = allowed_id
        self.listener = listener
        self.speaker = speaker
        self.loop: asyncio.AbstractEventLoop | None = None
        self.bot = None
        self.chat_id: int | None = None
        self.lock = asyncio.Lock()  # une seule question à la fois
        self._pending: dict[str, tuple[threading.Event, list[bool]]] = {}
        self._counter = 0
        self.brain: Brain = brain_factory(self._confirm_from_thread, self._status_from_thread)

    # --- Pont entre le cerveau (thread) et Telegram (asyncio) ---------------------

    def _call_soon(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _send_and_wait(self, coro, timeout: float = 15) -> None:
        """Depuis le thread du cerveau : envoie et attend que ce soit parti,
        pour que les messages arrivent dans le bon ordre."""
        try:
            self._call_soon(coro).result(timeout)
        except Exception as exc:
            log.warning("Message Telegram non envoyé : %s", exc)

    def _status_from_thread(self, text: str) -> None:
        if self.chat_id is not None:
            self._send_and_wait(self.bot.send_message(self.chat_id, f"⏳ {text}"))

    def _confirm_from_thread(self, description: str) -> bool:
        """Appelé par le cerveau : envoie des boutons Oui/Non et attend la réponse."""
        self._counter += 1
        key = str(self._counter)
        event, answer = threading.Event(), [False]
        self._pending[key] = (event, answer)
        buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Oui", callback_data=f"ok:{key}"),
            InlineKeyboardButton("❌ Non", callback_data=f"no:{key}"),
        ]])
        self._send_and_wait(self.bot.send_message(
            self.chat_id, f"⚠️ {description}\n{persona.confirm_question()}", reply_markup=buttons))
        if not event.wait(CONFIRM_TIMEOUT_S):
            self._send_and_wait(self.bot.send_message(self.chat_id, "⌛ Pas de réponse, j'annule."))
        self._pending.pop(key, None)
        return answer[0]

    def notify_owner(self, text: str) -> None:
        """Message spontané au propriétaire (rappels). Appelé depuis un thread."""
        if self.allowed_id is None or self.loop is None or self.bot is None:
            log.warning("Rappel non envoyé (bot pas encore prêt) : %s", text)
            return
        self._send_and_wait(self.bot.send_message(self.allowed_id, text))

    async def on_startup(self, app: Application) -> None:
        # Mémorise le bot et la boucle dès le démarrage : les rappels doivent
        # partir même si aucun message n'a encore été reçu.
        self.bot = app.bot
        self.loop = asyncio.get_running_loop()

    # --- Sécurité --------------------------------------------------------------

    async def _authorized(self, update: Update) -> bool:
        user = update.effective_user
        if self.allowed_id is None:
            await update.effective_message.reply_text(
                f"Configuration : ton identifiant Telegram est {user.id}.\n"
                f"Ajoute JARVIS_TELEGRAM_ID={user.id} dans le fichier .env, puis relance le bot.")
            return False
        if user.id != self.allowed_id:
            log.warning("Accès refusé à l'utilisateur %s", user.id)
            await update.effective_message.reply_text("Désolé, je ne parle qu'à mon propriétaire.")
            return False
        return True

    # --- Gestion des messages ----------------------------------------------------

    async def _answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                      text: str, as_voice: bool) -> None:
        self.bot = context.bot
        self.loop = asyncio.get_running_loop()
        self.chat_id = update.effective_chat.id
        async with self.lock:
            await context.bot.send_chat_action(self.chat_id, ChatAction.TYPING)
            reply = await asyncio.to_thread(self.brain.reply, text) or "…"
        for start in range(0, len(reply), TELEGRAM_MAX_LEN):
            await update.effective_message.reply_text(reply[start:start + TELEGRAM_MAX_LEN])
        if as_voice and self.speaker is not None:
            await self._send_voice(context, reply)

    async def _send_voice(self, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        from voice import wav_to_ogg_opus

        with tempfile.TemporaryDirectory() as tmp:
            wav, ogg = Path(tmp) / "r.wav", Path(tmp) / "r.ogg"
            try:
                await asyncio.to_thread(self.speaker.synthesize, text, wav)
                await asyncio.to_thread(wav_to_ogg_opus, wav, ogg)
            except Exception as exc:  # la réponse écrite est déjà partie
                log.warning("Vocal impossible : %s", exc)
                return
            with ogg.open("rb") as f:
                await context.bot.send_voice(self.chat_id, voice=f)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._authorized(update):
            await self._answer(update, context, update.effective_message.text, as_voice=False)

    async def on_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._authorized(update):
            return
        if self.listener is None:
            await update.effective_message.reply_text(
                "Les vocaux ne sont pas activés (installe les dépendances voix).")
            return
        from voice import decode_audio

        media = update.effective_message.voice or update.effective_message.audio
        data = bytes(await (await media.get_file()).download_as_bytearray())
        text = await asyncio.to_thread(lambda: self.listener.transcribe(decode_audio(data)))
        if not text:
            await update.effective_message.reply_text("Je n'ai rien entendu, tu peux répéter ?")
            return
        await update.effective_message.reply_text(f"🎤 « {text} »")
        await self._answer(update, context, text, as_voice=True)

    async def on_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if update.effective_user.id != self.allowed_id:
            await query.answer("Non autorisé.")
            return
        choice, _, key = (query.data or "").partition(":")
        pending = self._pending.get(key)
        await query.answer()
        if pending is None:
            await query.edit_message_text(f"{query.message.text}\n\n(Demande expirée.)")
            return
        event, answer = pending
        answer[0] = choice == "ok"
        event.set()
        verdict = "✅ Confirmé" if answer[0] else "❌ Annulé"
        await query.edit_message_text(f"{query.message.text}\n\n{verdict}")

    async def on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._authorized(update):
            await update.effective_message.reply_text(
                f"{persona.greeting()}\nÉcrivez-moi ou envoyez-moi un vocal.\n"
                "/memoire : ce que je sais de toi\n/nouveau : nouvelle conversation")

    async def on_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._authorized(update):
            await update.effective_message.reply_text(
                "Ce que je sais de toi :\n" + self.brain.memory.as_text())

    async def on_reset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._authorized(update):
            self.brain.reset()
            await update.effective_message.reply_text("C'est reparti à zéro. (Ma mémoire est conservée.)")

    def register(self, app: Application) -> None:
        # block=False : le bot reste réactif (boutons Oui/Non) pendant que Jarvis réfléchit.
        app.add_handler(CommandHandler("start", self.on_start))
        app.add_handler(CommandHandler("memoire", self.on_memory))
        app.add_handler(CommandHandler("nouveau", self.on_reset))
        app.add_handler(CallbackQueryHandler(self.on_button))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text, block=False))
        app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self.on_voice, block=False))


def make_cameras(gemini):
    """Caméras par adresse de flux (publiques ou à toi), décrites par la vision locale/Gemini."""
    import config as _c
    from camera import CameraBook, CameraManager
    from vision import VisionRouter

    router = VisionRouter(gemini=gemini)
    describe = router.describe if router.available else None
    return CameraManager(CameraBook(_c.CAMERAS_FILE), describe=describe)


def make_faces(drone):
    """Reconnaissance de visages (locale), si activée. Regarde la vue du drone si présent."""
    import config as _c
    if not _c.FACES:
        return None, None
    from faces import FaceRecognitionEngine, FaceStore, Recognizer

    recognizer = Recognizer(FaceRecognitionEngine(), FaceStore(_c.FACES_FILE))
    frame = (lambda: drone.c.frame()) if drone is not None else None
    return recognizer, frame


def make_drone(gemini):
    """Le drone : simulateur (démo) ou vrai Parrot ANAFI. La vision passe par Gemini si dispo."""
    import config as _c
    if _c.DRONE in ("0", ""):
        return None
    from drone import AnafiController, DronePilot, MavlinkController, SimDrone
    if _c.DRONE == "sim":
        controller = SimDrone()
    elif _c.DRONE == "mavlink":
        controller = MavlinkController()
    else:
        controller = AnafiController()
    from vision import VisionRouter
    router = VisionRouter(gemini=gemini)
    describe = router.describe if router.available else None
    inf = float("inf")
    if _c.DRONE == "sim":
        # Simulateur : aucune limite, rien à confirmer (c'est virtuel).
        return DronePilot(controller, describe=describe, step_max=inf, alt_max=inf,
                          alt_legal=inf, dist_legal=inf, dist_max=inf)
    # Vrai vol : libre sous la limite légale ; au-dessus, Jarvis demande confirmation,
    # jusqu'au plafond absolu.
    return DronePilot(controller, describe=describe, step_max=_c.DRONE_STEP_MAX,
                      alt_legal=_c.DRONE_ALT_MAX, alt_max=_c.DRONE_ALT_CEILING,
                      dist_legal=_c.DRONE_DIST_MAX, dist_max=_c.DRONE_DIST_CEILING)


def gemini_advisor():
    """Gemini en « deuxième avis », à côté de Claude. Préfère la clé API, sinon l'abonnement (CLI)."""
    import config as _c
    if _c.RENFORT.startswith("gemini"):
        return None  # Gemini est déjà le renfort principal
    if _c.GEMINI_KEY:
        return GeminiBackend()
    if _c.GEMINI_CLI_ENABLE:
        return GeminiCliBackend()
    return None


def setup_logging() -> None:
    fmt = "%(asctime)s %(name)s %(message)s"
    if sys.stderr is None:  # lancé en arrière-plan (pythonw.exe) : journal dans un fichier
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format=fmt,
                            filename=config.DATA_DIR / "telegram_bot.log", encoding="utf-8")
    else:
        logging.basicConfig(level=logging.INFO, format=fmt)


def main() -> None:
    setup_logging()
    logging.getLogger("httpx").setLevel(logging.WARNING)  # n'affiche pas le jeton dans les logs

    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise SystemExit("❌ Il manque TELEGRAM_TOKEN dans le fichier .env (voir le README).")
    if config.OFFLINE:
        raise SystemExit("❌ Le bot Telegram passe par internet : désactive JARVIS_HORS_LIGNE.")
    raw_id = os.environ.get("JARVIS_TELEGRAM_ID", "").strip()
    allowed_id = int(raw_id) if raw_id else None

    client = check_ollama(wait_s=180)  # au démarrage du PC, Ollama peut être lent à se lancer
    memory = Memory(config.MEMORY_FILE)
    claude = ClaudeBridge()

    listener = speaker = None
    try:
        from voice import Listener, Speaker

        listener, speaker = Listener(), Speaker()
    except Exception as exc:
        log.warning("Voix désactivée (%s) : le bot répondra par écrit uniquement.", exc)

    reminders, lists = Reminders(config.REMINDERS_FILE), Lists(config.LISTS_FILE)
    sentinel = Sentinel(config.SENTINEL_FILE) if config.SENTINEL else None
    home = SmartHome()
    gemini = gemini_advisor()
    drone = make_drone(gemini)
    faces, face_frame = make_faces(drone)
    cameras = make_cameras(gemini)

    def brain_factory(confirm, on_status):
        tools = build_tools(memory, claude, on_status=on_status, reminders=reminders, lists=lists,
                            sentinel=sentinel, home=home,
                            agent=claude if config.AGENT else None, gemini=gemini, drone=drone,
                            faces=faces, face_frame=face_frame, cameras=cameras)
        return Brain(client, tools, memory, confirm)

    jarvis = TelegramJarvis(brain_factory, allowed_id, listener, speaker)
    app = (Application.builder().token(token).concurrent_updates(True)
           .post_init(jarvis.on_startup).build())
    jarvis.register(app)
    ReminderWatcher(reminders, notify=jarvis.notify_owner).start()
    Proactive(reminders, lists, security=sentinel.check if sentinel else None,
              notify=jarvis.notify_owner).start()
    log.info("Jarvis est en ligne sur Telegram (Ctrl+C pour arrêter).")
    if allowed_id is None:
        log.info("Envoie /start au bot : il te donnera ton identifiant à mettre dans .env.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
