# Drone DIY avec mini-Jarvis embarqué

L'idée : un drone que tu construis, avec un **petit ordinateur à bord** qui fait tourner
Jarvis. Le drone réagit tout seul (voir, éviter, tenir une cible) et appelle le Jarvis
du sol ou le cloud pour le difficile — la même architecture que sur ton ordinateur.

> ⚠️ Un drone qui décide en partie seul, c'est sérieux. Garde-le toujours à vue, respecte
> les règles de vol de ton pays, et teste **tout** dans le simulateur avant de voler.

## L'architecture

```
        DRONE
  ┌───────────────────────────────┐
  │  Caméra ──► Ordinateur de bord │   (Raspberry Pi 5 ou NVIDIA Jetson)
  │            = mini-Jarvis       │   - vision locale (voir, détecter)
  │              │                 │   - réflexes rapides (éviter, tenir)
  │              ▼  MAVLink        │   - exécute tes ordres
  │     Contrôleur de vol (Pixhawk)│   (ArduPilot ou PX4)
  │              │                 │
  │     Moteurs, GPS, batterie     │
  └──────────────┬────────────────┘
                 │  Wi-Fi / 4G / radio
                 ▼
        JARVIS DU SOL (mini-PC)  ──►  Claude / Gemini (le difficile)
```

- **L'ordinateur de bord** fait le rapide et le local : voir, réagir, piloter.
- **Le sol et le cloud** font le lent et le compliqué : raisonner, décider, rédiger.
- La liaison se fait en **MAVLink**, le langage standard des drones ArduPilot/PX4.
  Jarvis parle déjà MAVLink (`JARVIS_DRONE=mavlink`).

## Le matériel (exemple)

| Pièce | Choix conseillé | Rôle |
|---|---|---|
| Cadre + moteurs + hélices | Kit quadricoptère 5" ou 7" | Le corps |
| Contrôleur de vol | **Pixhawk** (ArduPilot ou PX4) | Stabilise, pilote les moteurs |
| GPS + boussole | Module GPS pour Pixhawk | Position, retour maison |
| Ordinateur de bord | **Raspberry Pi 5** (léger) ou **NVIDIA Jetson Orin Nano** (vision rapide) | Le mini-Jarvis |
| Caméra | Caméra CSI (Pi) ou USB | Les yeux |
| Liaison | Wi-Fi longue portée, ou 4G, ou radio télémétrie | Parler au sol |
| Batterie | LiPo adaptée au cadre | L'énergie |

Le Jetson est mieux si tu veux de la **vision en temps réel** (détecter, suivre) ; le Pi 5
suffit pour voir « de temps en temps » et piloter.

## Le logiciel

1. **Contrôleur de vol** : installe **ArduPilot** (ou PX4) sur le Pixhawk, règle-le avec
   *Mission Planner* ou *QGroundControl*. Fais les réglages de sécurité : **geofence**
   (barrière virtuelle), **retour maison** si batterie faible ou liaison perdue.
2. **Ordinateur de bord** : installe le mini-Jarvis avec le script prévu. Depuis le
   mini-PC, une fois l'ordinateur de bord relié au réseau :
   ```bash
   ssh <user>@<adresse-du-drone> 'bash -s' < installer_embarque.sh
   ```
   Il installe un modèle **léger** (`qwen2.5:3b`), un modèle de **vision** (`moondream`),
   `pymavlink`, et écrit un `.env` embarqué (`JARVIS_DRONE=mavlink`, vision locale,
   `JARVIS_DRONE_URL=udp:127.0.0.1:14550`). **Claude Code, sur le mini-PC, peut lancer
   cette installation à distance** pour toi. L'ordinateur de bord est petit : modèle léger
   pour voir et réagir vite, le difficile part au Jarvis du sol ou au cloud.
3. **Vision** : la caméra alimente la vision locale de Jarvis (voir [README](README.md)).

## Tester SANS risque (indispensable)

Avant d'acheter un moteur, teste tout dans le **simulateur ArduPilot (SITL)** — c'est
gratuit et sans danger. Le vrai code de vol de Jarvis y pilote un drone virtuel.

```bash
# installe ArduPilot SITL (voir ardupilot.org), lance un quadri simulé, puis :
pip install pymavlink
# dans .env : JARVIS_DRONE=mavlink et JARVIS_DRONE_URL=udp:127.0.0.1:14550
.venv/bin/python main.py        # « décolle », « avance de 2 mètres », « atterris »...
```

Tu verras Jarvis armer, décoller, se déplacer et rentrer, dans le simulateur.

## Sécurité (à ne pas négliger)

- **Confirmation avant le décollage**, toujours (Jarvis le fait déjà).
- **« Arrête-toi » = retour maison automatique** (RTL) : réflexe sûr intégré.
- **Déplacements bornés** (5 m par ordre, 30 m d'altitude).
- **Geofence** réglée dans ArduPilot : le drone ne peut pas sortir d'une zone.
- **Retour maison** automatique si batterie faible ou liaison perdue (réglé dans ArduPilot).
- Pas d'autonomie totale : Jarvis exécute tes ordres et réagit, il ne part pas en mission seul.
- **Garde le drone à vue** et respecte la loi (zones, altitude, survol de personnes).

## Par où commencer

1. **Simulateur ArduPilot SITL** + Jarvis en mode `mavlink` : tu pilotes un drone virtuel à la voix.
2. Quand c'est au point, le matériel : Pixhawk + Pi/Jetson + caméra.
3. Premiers vols : en extérieur dégagé, batterie neuve, geofence serrée, à vue.
