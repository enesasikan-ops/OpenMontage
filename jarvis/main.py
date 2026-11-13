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
    parser.add_argument("--voix", action="store_true", help="mode vocal (micro + haut-parleur)")
    args = parser.parse_args()

    client = check_ollama()
    memory = Memory(config.MEMORY_FILE)
    claude = ClaudeBridge()

    listener = speaker = None
    if args.voix:
        from voice import Listener, Speaker, is_yes

        listener, speaker = Listener(), Speaker()

    def say(text: str) -> None:
        print(f"🤖 Jarvis : {text}")
        if speaker:
            speaker.say(text)

    def hear() -> str:
        if listener:
            text = listener.listen()
            print(f"🧑 Toi : {text}")
            return text
        return input("🧑 Toi : ")

    def confirm(description: str) -> bool:
        say(f"{description} Je confirme ?")
        answer = hear()
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
    print("Dis « au revoir » pour quitter.\n")
    say(f"Bonjour {config.USER_NAME}, je t'écoute.")

    while True:
        try:
            text = hear().strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not text:
            continue
        if any(w in text.lower() for w in STOP_WORDS):
            say("À plus tard !")
            break
        say(brain.reply(text))


if __name__ == "__main__":
    main()
