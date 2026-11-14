"""Enrôle ta voix pour l'authentification des actions sensibles.

    python enroll_voice.py            # enrôle le propriétaire (JARVIS_VOIX_PROPRIO)
    python enroll_voice.py papa 5     # enrôle « papa » avec 5 échantillons

On enregistre quelques phrases au micro, on en calcule l'empreinte (locale) et on la
range dans empreintes_vocales.json. Rien ne sort de l'ordinateur. Varie un peu tes
phrases et ton intonation pour une empreinte robuste.
"""

import sys

import config
from voice import Listener
from voiceprint import SpeakerVerifier, VoiceStore


def main() -> None:
    nom = sys.argv[1] if len(sys.argv) > 1 else config.VOICE_OWNER
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    listener = Listener()
    verifier = SpeakerVerifier(VoiceStore(config.VOICE_FILE), seuil=config.VOICE_SEUIL)
    print(f"Enrôlement de « {nom} » — {n} échantillons. Parle naturellement.\n")

    audios = []
    for i in range(1, n + 1):
        print(f"Échantillon {i}/{n} :")
        audio = listener.record()
        if len(audio) < 16000 // 2:   # moins d'une demi-seconde
            print("  (trop court, on recommence)")
            continue
        audios.append(audio)

    ajoutes = verifier.enroler(nom, audios)
    print(f"\n✅ {ajoutes} empreinte(s) enregistrée(s) pour « {nom} » dans {config.VOICE_FILE}.")
    if ajoutes:
        print("Teste : demande une action sensible — seule ta voix l'autorisera.")


if __name__ == "__main__":
    main()
