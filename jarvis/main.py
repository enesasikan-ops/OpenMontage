"""Point d'entrée de Jarvis.

    python main.py          # mode clavier (pour tester)
    python main.py --voix   # mode vocal : micro + voix
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import config  # noqa: E402  (après load_dotenv pour lire le .env)
import persona  # noqa: E402
from brain import Brain  # noqa: E402
from claude_bridge import ClaudeBridge  # noqa: E402
from memory import Memory  # noqa: E402
from skills import Lists, Reminders, ReminderWatcher  # noqa: E402
from tools import build_tools  # noqa: E402

STOP_WORDS = ("au revoir", "bonne nuit jarvis", "quitter", "exit", "stop jarvis")


def model_installed(wanted: str, installed: set[str]) -> bool:
    """« qwen3:30b-a3b » doit être installé tel quel ; « mistral-small3.2 » = « :latest »."""
    full = wanted if ":" in wanted else f"{wanted}:latest"
    return full in installed


def check_ollama(wait_s: int = 0):
    """Vérifie qu'Ollama répond et que le modèle est installé.

    wait_s : au démarrage du PC, Ollama peut mettre un moment à se lancer ;
    on patiente jusqu'à wait_s secondes avant d'abandonner.
    """
    import time

    import ollama

    client = ollama.Client(host=config.OLLAMA_HOST)
    deadline = time.monotonic() + wait_s
    while True:
        try:
            installed = {m.model for m in client.list().models}
            break
        except Exception:
            if time.monotonic() >= deadline:
                sys.exit("❌ Ollama ne répond pas. Ouvre l'app Ollama (ou lance « ollama serve »).")
            time.sleep(5)
    if not model_installed(config.LOCAL_MODEL, installed):
        sys.exit(f"❌ Le modèle « {config.LOCAL_MODEL} » n'est pas installé.\n"
                 f"   Lance : ollama pull {config.LOCAL_MODEL}")
    return client


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis, assistant personnel")
    parser.add_argument("--voix", action="store_true",
                        help="mode vocal : Entrée pour parler, Entrée pour finir")
    parser.add_argument("--mains-libres", action="store_true",
                        help="mode vocal sans clavier : dis « Jarvis » dans ta phrase")
    args = parser.parse_args()

    client = check_ollama(wait_s=180 if args.mains_libres else 0)
    memory = Memory(config.MEMORY_FILE)
    claude = ClaudeBridge()

    listener = speaker = hands = None
    if args.voix or args.mains_libres:
        from voice import Listener, Speaker, is_yes

        listener, speaker = Listener(), Speaker()
    if args.mains_libres:
        from handsfree import HandsFree, MicSource, is_sleep

        mic = MicSource()
        hands = HandsFree(listener, mic.frames(), flush=mic.flush)

    def say(text: str) -> None:
        print(f"🤖 Jarvis : {text}")
        if hands:
            hands.mute()  # Jarvis ne doit pas s'écouter parler
        try:
            if speaker:
                speaker.say(text)
        finally:
            if hands:
                hands.spoke()

    def hear() -> str | None:
        if hands:
            text = hands.next_command()
        elif listener:
            text = listener.listen()
        else:
            return input("🧑 Toi : ")
        print(f"🧑 Toi : {text if text is not None else 'Jarvis ?'}")
        return text

    def confirm(description: str) -> bool:
        say(f"{description} {persona.confirm_question()}")
        if hands:
            answer = hands.next_utterance()
            print(f"🧑 Toi : {answer}")
            return is_yes(answer)
        answer = hear() or ""
        return is_yes(answer) if listener else answer.strip().lower() in ("o", "oui", "y", "yes", "ok")

    reminders, lists = Reminders(config.REMINDERS_FILE), Lists(config.LISTS_FILE)
    tools = build_tools(memory, claude, on_status=say, reminders=reminders, lists=lists)
    brain = Brain(client, tools, memory, confirm)
    ReminderWatcher(reminders, notify=lambda text: say(f"\n{text}")).start()

    if claude.available:
        renfort = f"renfort : {claude.name}"
    else:
        renfort = f"sans renfort ({claude.backend.unavailable_reason()})"
    print(f"Jarvis prêt — cerveau local : {config.LOCAL_MODEL}, {renfort}.")
    if config.OFFLINE:
        print("🔒 Mode 100 % hors ligne : rien ne sort de cet ordinateur.")
    if hands:
        print("Mains libres : dis « Jarvis » dans ta phrase. « Merci Jarvis » termine la "
              "conversation. Ctrl+C pour quitter.\n")
    else:
        print("Dis « au revoir » pour quitter.\n")
    say(persona.greeting())

    while True:
        try:
            text = hear()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if hands:
            if text is None:  # on a juste dit « Jarvis »
                say(persona.wake_ack())
                continue
            if is_sleep(text):  # « merci Jarvis » : il se met en veille, sans s'arrêter
                say(persona.standby())
                hands.sleep()
                continue
        text = (text or "").strip()
        if not text:
            continue
        if not hands and any(w in text.lower() for w in STOP_WORDS):
            say(persona.farewell())
            break
        say(brain.reply(text) or persona.not_understood())


if __name__ == "__main__":
    main()
