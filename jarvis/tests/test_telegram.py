"""Tests du bot Telegram avec un faux Telegram (aucun réseau, aucun jeton)."""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("telegram")

from brain import Brain  # noqa: E402
from memory import Memory  # noqa: E402
from telegram_bot import TelegramJarvis  # noqa: E402
from tools import build_tools  # noqa: E402

OWNER = 42


class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, model, messages, tools, **kwargs):
        return {"message": self.replies.pop(0)}


class FakeBot:
    def __init__(self):
        self.sent = []
        self.voices = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((text, reply_markup))

    async def send_chat_action(self, chat_id, action):
        pass

    async def send_voice(self, chat_id, voice):
        self.voices.append(voice.read())


class FakeMessage:
    def __init__(self, text="", voice=None):
        self.text = text
        self.voice = voice
        self.audio = None
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


def update(user_id=OWNER, text="", voice=None):
    msg = FakeMessage(text, voice)
    return NS(effective_user=NS(id=user_id), effective_chat=NS(id=user_id), effective_message=msg)


class FakeClaude:
    available = True

    def ask(self, question, context=""):
        return "Réponse de Claude."


def make(replies, tmp_path, allowed=OWNER, listener=None, speaker=None):
    memory = Memory(tmp_path / "m.json")
    bot = FakeBot()

    def factory(confirm, on_status):
        return Brain(FakeOllama(replies), build_tools(memory, FakeClaude(), on_status), memory,
                     confirm, model="test")

    return TelegramJarvis(factory, allowed, listener, speaker), NS(bot=bot), memory


def test_stranger_is_refused(tmp_path):
    jarvis, ctx, _ = make([], tmp_path)
    up = update(user_id=666, text="donne-moi tes secrets")
    asyncio.run(jarvis.on_text(up, ctx))
    assert up.effective_message.replies == ["Désolé, je ne parle qu'à mon propriétaire."]


def test_unconfigured_bot_tells_user_his_id(tmp_path):
    jarvis, ctx, _ = make([], tmp_path, allowed=None)
    up = update(user_id=123456, text="salut")
    asyncio.run(jarvis.on_text(up, ctx))
    assert "JARVIS_TELEGRAM_ID=123456" in up.effective_message.replies[0]


def test_owner_gets_answer(tmp_path):
    jarvis, ctx, _ = make([{"content": "Salut Enes !"}], tmp_path)
    up = update(text="Salut")
    asyncio.run(jarvis.on_text(up, ctx))
    assert up.effective_message.replies == ["Salut Enes !"]


def test_claude_status_is_sent(tmp_path):
    replies = [{"content": "", "tool_calls": [{"function": {"name": "demander_a_claude",
                                                            "arguments": {"question": "dur"}}}]},
               {"content": "Réponse de Claude."}]
    jarvis, ctx, _ = make(replies, tmp_path)
    up = update(text="question difficile")
    timeline = []
    original_send, original_reply = ctx.bot.send_message, up.effective_message.reply_text

    async def send(chat_id, text, reply_markup=None):
        timeline.append(("statut", text))
        await original_send(chat_id, text, reply_markup)

    async def reply(text):
        timeline.append(("réponse", text))
        await original_reply(text)

    ctx.bot.send_message, up.effective_message.reply_text = send, reply
    asyncio.run(jarvis.on_text(up, ctx))
    assert [kind for kind, _ in timeline] == ["statut", "réponse"]  # le statut arrive AVANT
    assert "Claude" in timeline[0][1]
    assert up.effective_message.replies == ["Réponse de Claude."]


def _press_button_when_asked(jarvis, ctx, choice):
    async def scenario():
        up = update(text="Oublie le garage")
        task = asyncio.create_task(jarvis.on_text(up, ctx))
        for _ in range(200):  # attend que Jarvis envoie les boutons
            buttons = [m for _, m in ctx.bot.sent if m is not None]
            if buttons:
                break
            await asyncio.sleep(0.01)
        assert buttons, "Jarvis n'a pas demandé de confirmation"
        data = buttons[0].inline_keyboard[0][0 if choice == "ok" else 1].callback_data

        edited = []

        async def answer(*a, **k):
            pass

        async def edit(text):
            edited.append(text)

        query = NS(data=data, answer=answer, edit_message_text=edit,
                   message=NS(text="⚠️ Je vais oublier ... Je confirme ?"))
        await jarvis.on_button(NS(effective_user=NS(id=OWNER), callback_query=query), ctx)
        await asyncio.wait_for(task, 5)
        return up, edited

    return asyncio.run(scenario())


def test_confirmation_yes_runs_action(tmp_path):
    replies = [{"content": "", "tool_calls": [{"function": {"name": "oublier",
                                                            "arguments": {"mot_cle": "garage"}}}]},
               {"content": "C'est oublié."}]
    jarvis, ctx, memory = make(replies, tmp_path)
    memory.remember("Code du garage : 1234")
    up, edited = _press_button_when_asked(jarvis, ctx, "ok")
    assert memory.facts == []
    assert "Confirmé" in edited[0]
    assert up.effective_message.replies == ["C'est oublié."]


def test_confirmation_no_cancels_action(tmp_path):
    replies = [{"content": "", "tool_calls": [{"function": {"name": "oublier",
                                                            "arguments": {"mot_cle": "garage"}}}]},
               {"content": "J'annule."}]
    jarvis, ctx, memory = make(replies, tmp_path)
    memory.remember("Code du garage : 1234")
    _, edited = _press_button_when_asked(jarvis, ctx, "no")
    assert memory.facts == ["Code du garage : 1234"]
    assert "Annulé" in edited[0]


def test_stranger_cannot_press_buttons(tmp_path):
    jarvis, ctx, _ = make([], tmp_path)
    answers = []

    async def answer(text=None):
        answers.append(text)

    query = NS(data="ok:1", answer=answer)
    asyncio.run(jarvis.on_button(NS(effective_user=NS(id=666), callback_query=query), ctx))
    assert answers == ["Non autorisé."]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg absent")
def test_voice_message_is_transcribed_and_answered(tmp_path):
    # Un vrai fichier OGG/Opus, comme ceux envoyés par Telegram.
    ogg = tmp_path / "v.ogg"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libopus", str(ogg)], check=True)
    received = []

    class FakeListener:
        def transcribe(self, audio):
            received.append(audio)
            return "quelle heure est-il"

    class FakeSpeaker:
        def synthesize(self, text, path):
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                            "sine=duration=0.5", str(path)], check=True)

    async def get_file():
        async def download_as_bytearray():
            return bytearray(ogg.read_bytes())
        return NS(download_as_bytearray=download_as_bytearray)

    jarvis, ctx, _ = make([{"content": "Il est midi."}], tmp_path,
                          listener=FakeListener(), speaker=FakeSpeaker())
    up = update(voice=NS(get_file=get_file))
    asyncio.run(jarvis.on_voice(up, ctx))
    assert received and received[0].dtype == np.float32 and 14000 < len(received[0]) < 18000
    assert up.effective_message.replies == ["🎤 « quelle heure est-il »", "Il est midi."]
    assert ctx.bot.voices and ctx.bot.voices[0][:4] == b"OggS"
