"""Alertes de Jarvis via Signal (chiffré bout en bout), avec signal-cli.

Envoi seulement (alertes du gardien). Pour *parler* à Jarvis par Signal (deux sens),
il faut signal-cli en mode démon JSON-RPC : voir signal_bot.py (à venir).

Réglages (dans .env) :
  JARVIS_SIGNAL_CLI          chemin de signal-cli (défaut : "signal-cli", pris dans le PATH)
  JARVIS_SIGNAL_EXPEDITEUR   numéro qui envoie (le compte signal-cli), ex. +33600000000
  JARVIS_SIGNAL_DESTINATAIRE numéro qui reçoit (le vôtre), ex. +33611111111

Mise en place (une fois) : voir la fin du fichier.
"""

from __future__ import annotations

import logging
import subprocess

import config

log = logging.getLogger(__name__)

SIGNAL_CLI = config._env("JARVIS_SIGNAL_CLI", "signal-cli")
EXPEDITEUR = config._env("JARVIS_SIGNAL_EXPEDITEUR", "")
DESTINATAIRE = config._env("JARVIS_SIGNAL_DESTINATAIRE", "")
DELAI_S = 30  # signal-cli démarre une JVM : on laisse de la marge


def _envoyer(texte: str, chemin_photo: str | None = None) -> bool:
    """Envoie un message Signal. Ne lève jamais : renvoie False en cas d'échec."""
    if not EXPEDITEUR or not DESTINATAIRE:
        log.warning("Signal non configuré (JARVIS_SIGNAL_EXPEDITEUR / _DESTINATAIRE absents)")
        return False

    cmd = [SIGNAL_CLI, "--account", EXPEDITEUR, "send", "--message", texte]
    if chemin_photo:
        cmd += ["--attachment", chemin_photo]
    cmd.append(DESTINATAIRE)

    try:
        subprocess.run(
            cmd, check=True, timeout=DELAI_S,
            capture_output=True, text=True,
        )
        return True
    except FileNotFoundError:
        log.error("signal-cli introuvable (%s). Installez-le ou corrigez JARVIS_SIGNAL_CLI.", SIGNAL_CLI)
    except subprocess.TimeoutExpired:
        log.error("signal-cli n'a pas répondu en %s s", DELAI_S)
    except subprocess.CalledProcessError as e:
        log.error("signal-cli a échoué : %s", (e.stderr or "").strip())
    return False


def envoyer_signal_texte(description: str) -> bool:
    """Alerte texte seul : aucune image ne quitte la maison."""
    return _envoyer(f"🚨 Mouvement inconnu\n\n{description}"[:2000])


def envoyer_signal_photo(chemin_image: str, description: str) -> bool:
    """Alerte photo + texte."""
    return _envoyer(f"🚨 Mouvement inconnu détecté\n\n{description}"[:2000], chemin_photo=chemin_image)


def alerter_signal(chemin_image: str, description: str, client_local, modele: str) -> None:
    """Jarvis choisit photo+texte ou texte seul (repli sûr sur texte).

    Réutilise la même décision que pour Telegram : voir _jarvis_veut_la_photo.
    """
    from gardien import _jarvis_veut_la_photo  # la décision vit avec le gardien

    if _jarvis_veut_la_photo(description, client_local, modele):
        if not envoyer_signal_photo(chemin_image, description):
            envoyer_signal_texte(description)  # échec photo -> au moins le texte
    else:
        envoyer_signal_texte(description)


# --- Mise en place (une seule fois) ------------------------------------------
# 1. Installer signal-cli (https://github.com/AsamK/signal-cli).
# 2. Relier Jarvis à votre téléphone (le plus simple, pas de 2e numéro) :
#       signal-cli link -n "Jarvis"
#    Une adresse « sgnl://linkdevice?... » s'affiche. Transformez-la en QR code,
#    puis sur le téléphone : Signal > Réglages > Appareils liés > Lier un appareil.
#    Jarvis envoie alors depuis VOTRE numéro ; mettez le même numéro dans
#    EXPEDITEUR et DESTINATAIRE pour recevoir les alertes dans votre « Notes »
#    (conversation avec soi-même).
#    Variante : enregistrer un numéro dédié (signal-cli register), si vous en avez un.
# 3. Tester :  python -c "import signal_notify as s; print(s.envoyer_signal_texte('Test Jarvis'))"
