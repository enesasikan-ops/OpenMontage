"""Les outils de Jarvis.

Chaque outil peut exiger une confirmation : Jarvis décrit alors ce qu'il va
faire et attend un « oui » avant d'agir. C'est le garde-fou sur les ACTIONS
(envoyer, supprimer, payer, ouvrir...), la conversation, elle, reste libre.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import config
import persona
from claude_bridge import ClaudeBridge
from memory import Memory

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[..., str]
    # Si défini : phrase décrivant l'action, lue à l'utilisateur pour confirmation.
    confirm: Callable[..., str] | None = None

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _now_text() -> str:
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    return (f"Nous sommes le {JOURS[now.weekday()]} {now.day} {MOIS[now.month - 1]} "
            f"{now.year}, il est {now.hour}h{now.minute:02d}.")


def build_tools(memory: Memory, claude: ClaudeBridge,
                on_status: Callable[[str], None], reminders=None, lists=None,
                sentinel=None, home=None, web=True, agent=None,
                gemini=None, drone=None, faces=None, face_frame=None,
                cameras=None, growth=None, proposals=None, plugins=True, watchdog=None) -> dict[str, Tool]:
    """reminders / lists : stockages des compétences (skills.py). Sans eux, outils de base seuls."""
    def ask_claude(question: str, contexte: str = "") -> str:
        on_status(persona.asking_claude())
        return claude.ask(question, contexte)

    tools = [
        Tool(
            name="heure_et_date",
            description="Donne la date et l'heure actuelles.",
            parameters={"type": "object", "properties": {}, "required": []},
            run=lambda: _now_text(),
        ),
        Tool(
            name="retenir",
            description=("Mémorise durablement un fait sur l'utilisateur ou ses projets "
                         "(préférence, info personnelle, rappel). À utiliser quand "
                         "l'utilisateur dit « retiens que... » ou partage une info utile."),
            parameters={
                "type": "object",
                "properties": {"fait": {"type": "string", "description": "Le fait à retenir, en une phrase."}},
                "required": ["fait"],
            },
            run=lambda fait: memory.remember(fait),
        ),
        Tool(
            name="oublier",
            description="Supprime de la mémoire les faits qui contiennent un mot-clé.",
            parameters={
                "type": "object",
                "properties": {"mot_cle": {"type": "string", "description": "Mot-clé des faits à oublier."}},
                "required": ["mot_cle"],
            },
            run=lambda mot_cle: memory.forget(mot_cle),
            confirm=lambda mot_cle: (
                f"Je vais oublier : {' ; '.join(memory.find(mot_cle)) or 'rien (aucun fait trouvé)'}."
            ),
        ),
        Tool(
            name="demander_a_claude",
            description=("Pose la question à Claude, une IA beaucoup plus puissante, via internet. "
                         "LE CHOIX POUR LA PRÉCISION : raisonnement complexe, maths, analyse fine, "
                         "conseils importants, rédaction (mail, document), CODE et correctifs, "
                         "sujets où tu n'es pas sûr, ou quand l'utilisateur dit « demande à Claude ». "
                         "Pour éplucher de TRÈS longs documents/logs d'un coup, préfère Gemini "
                         "(grand contexte). Ne l'utilise PAS pour les questions simples."),
            parameters={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "La question complète, reformulée clairement."},
                    "contexte": {"type": "string", "description": "Infos utiles de la conversation (facultatif)."},
                },
                "required": ["question"],
            },
            run=ask_claude,
        ),
    ]
    from council import build_planner_tools   # planificateur multi-angles (propose, n'exécute pas)

    tools += build_planner_tools(claude)
    from conscience import build_conscience_tools   # conscience de situation (relie les capteurs, réfléchit)

    tools += build_conscience_tools(home, claude)
    from consolidation import build_consolidation_tools   # « sommeil cognitif » : range la mémoire (propose)

    tools += build_consolidation_tools(memory, claude)
    from secondmodel import build_second_model_tools   # second modèle local consultable (ex. dolphin-llama3)

    tools += build_second_model_tools()
    if reminders is not None and lists is not None:
        from skills import build_skills  # import tardif : skills.py importe Tool d'ici

        tools += build_skills(reminders, lists, sentinel)
    if home is not None and home.configured:
        from smarthome import build_smarthome

        tools += build_smarthome(home)
        from vacuum import build_vacuum_tools

        tools += build_vacuum_tools(home)   # aspirateur robot (Valetudo via HA)
        from deterrent import build_deterrent_tools

        tools += build_deterrent_tools(home)   # arroseur anti-nuisibles (dissuasion par zone)
        from comfort import build_comfort_tools

        tools += build_comfort_tools(home)   # mode détente (ambiance apaisante, déclenché par toi)
        from habits import build_habit_tools

        tools += build_habit_tools(home)   # habitudes apprises (lecture seule : propose, n'agit pas)
        from vehicle import build_vehicle_tools

        tools += build_vehicle_tools(home)   # voiture connectée (position, serrures) via l'API constructeur
        from poolguard import build_pool_tools

        tools += build_pool_tools(home, on_status)   # surveillance piscine (armer/annuler l'urgence)
        from thermal import build_thermal_tools

        tools += build_thermal_tools(home)   # vigilance thermique (plaque oubliée, lecture seule)
        from presence import build_presence_tools

        tools += build_presence_tools(home)   # carte de présence (occupation anonyme par pièce)
        from audiofollow import build_audio_tools

        tools += build_audio_tools(home)   # le son qui suit de pièce en pièce (Snapcast + présence)
        from presence_sim import build_simulation_tools

        tools += build_simulation_tools(home)   # simulation de présence « vacances » (lumières/volets, jamais serrure)
        ask = getattr(claude, "ask", None)
        if callable(ask):   # créer des règles à la voix (nécessite le renfort pour traduire)
            from automations import build_automation_tools

            tools += build_automation_tools(home, ask)
    if web:
        from web import build_web_tools

        tools += build_web_tools()
    from people import build_people_tools   # mémoire par personne (toujours disponible, local)

    tools += build_people_tools()
    from pwstrength import build_pwcheck_tools   # robustesse d'un mot de passe / clé Wi-Fi (local)

    tools += build_pwcheck_tools()
    from preferences import build_preference_tools   # consignes de comportement dictées par toi

    tools += build_preference_tools()
    from archive import build_archive_tools   # mémoire d'archive cherchée à la demande (ne charge pas le prompt)

    tools += build_archive_tools()
    from liens import build_link_tools   # mémoire associative : relie les souvenirs entre eux (local)

    tools += build_link_tools(memory)
    from sightings import build_sighting_tools   # « qui as-tu vu ? » (journal des reconnaissances)

    tools += build_sighting_tools()
    from mower import build_mower_tools   # kill-switch visuel tondeuse (armer/arrêter), si configuré

    tools += build_mower_tools(on_status, home)
    from freebox import build_freebox_tools   # qui est sur le Wi-Fi (Freebox), si appairée

    tools += build_freebox_tools()
    from radius import build_radius_tools   # surveillance auth 802.1X (FreeRADIUS), si configuré

    tools += build_radius_tools()
    from starlink import build_starlink_tools   # état de l'Internet Starlink (WAN), si configuré

    tools += build_starlink_tools()
    from opnsense import build_opnsense_tools   # fil d'alarme bastion OPNsense (VLAN), si configuré

    tools += build_opnsense_tools()
    from robot import build_robot_tools   # robot mobile (ROS 2), si des lieux sont configurés

    tools += build_robot_tools()
    from crowdsec import build_crowdsec_tools   # point sécurité réseau (CrowdSec), si configuré

    tools += build_crowdsec_tools()
    from radio import build_radio_tools   # radio SDR : avion au-dessus (ADS-B), météo radio locale

    tools += build_radio_tools(home)
    from dronewatch import build_drone_tools   # veille aérienne (drones Remote ID), si configuré

    tools += build_drone_tools()
    from vulnscan import build_vulnscan_tools   # audit de posture réseau (détecte, n'attaque pas)

    tools += build_vulnscan_tools()
    if watchdog is not None:   # mode Sentinelle (armer/désarmer à la voix)
        from watchdog import build_watchdog_tools

        tools += build_watchdog_tools(watchdog)
    if drone is not None:
        from drone import build_drone_tools

        tools += build_drone_tools(drone)
    if faces is not None:
        from faces import build_face_tools

        tools += build_face_tools(faces, face_frame)
    if cameras is not None:
        from camera import build_camera_tools

        tools += build_camera_tools(cameras)
    if growth is not None:
        from growth import build_growth_tools

        tools += build_growth_tools(growth, agent=agent)
    if gemini is not None and gemini.available:
        def ask_gemini(question: str, contexte: str = "") -> str:
            on_status("Je demande à Gemini.")
            return gemini.ask(question, contexte)

        tools.append(Tool(
            name="demander_a_gemini",
            description=("Demande l'avis de Gemini, l'IA de Google. LE CHOIX POUR LE GRAND CONTEXTE : "
                         "éplucher de longs documents ou des logs entiers (un mois d'historique), "
                         "résumer de gros volumes. Aussi pour un deuxième avis, comparer avec Claude, "
                         "ou quand l'utilisateur demande Gemini. Pour du code ou un raisonnement précis, "
                         "préfère Claude. Gemini répond mais n'agit pas sur l'ordinateur."),
            parameters={"type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "La question, reformulée clairement."},
                            "contexte": {"type": "string", "description": "Infos utiles (facultatif)."}},
                        "required": ["question"]},
            run=ask_gemini,
        ))
    if agent is not None:
        on_status_agent = on_status

        def confier(tache: str) -> str:
            on_status_agent("Je confie ça à Claude, mon mentor. Un instant, il travaille.")
            return agent.delegate(tache)

        tools.append(Tool(
            name="confier_a_claude",
            description=("Confie une tâche IMPORTANTE à Claude, qui l'exécute vraiment sur l'ordinateur "
                         "(écrire du code, créer ou modifier des fichiers dans l'atelier, recherche "
                         "approfondie en plusieurs étapes). À utiliser pour « écris un programme qui... », "
                         "« crée-moi un script », une tâche longue et complexe. Pas pour une simple question "
                         "(utilise demander_a_claude) ni une action rapide."),
            parameters={"type": "object",
                        "properties": {"tache": {"type": "string",
                                       "description": "La tâche complète et précise à réaliser."}},
                        "required": ["tache"]},
            run=confier,
            confirm=lambda tache: f"Je vais confier à Claude, qui travaillera sur l'ordinateur : {tache}",
        ))
    if proposals is not None:
        from growth import build_proposal_tools

        tools += build_proposal_tools(proposals)
    if plugins:
        # Chargement simple au démarrage. En fonctionnement normal, c'est le PluginManager
        # (chargement à chaud) qui s'en charge : build_tools(..., plugins=False).
        from growth import load_plugins

        known = {t.name for t in tools}
        tools += [t for t in load_plugins() if t.name not in known]  # le cœur garde la priorité
    return {t.name: t for t in tools}
