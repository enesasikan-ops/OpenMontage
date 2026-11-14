# Sécurité de Jarvis — modèle de menaces

Ce document décrit la surface d'attaque de Jarvis, les protections en place et les zones à
tester. Il est destiné à un **test de sécurité autorisé, sur sa propre instance** (celle du
propriétaire). Il ne contient pas d'exploit : c'est une carte pour un audit défensif.

> Si le dépôt est **public**, ce document l'est aussi. Il décrit le modèle de sécurité, pas
> des secrets. Pour une instance personnelle, garder le dépôt **privé** reste conseillé.

## Vue d'ensemble

Jarvis tourne **en local** sur la machine du propriétaire. Un modèle local (Ollama) décide
et appelle des outils ; un renfort (Claude/Gemini) est sollicité pour le difficile. Tout ce
qui est sensible passe par une **confirmation** du propriétaire.

## Frontières de confiance

| Zone | Confiance | Remarque |
|---|---|---|
| Modèle local + outils | moyenne | le LLM choisit les outils ; une injection peut l'orienter |
| Renfort Claude/Gemini (CLI/API) | externe | sort du réseau ; ne reçoit jamais de secret |
| Plugins (`plugins/`) | **exécutés avec tous les droits** | voir « RCE par conception » |
| Messages entrants (Telegram/Signal) | non fiables | filtrés à un seul expéditeur autorisé |
| Pages web / caméras / domotique | non fiables | données externes, jamais des instructions |
| 2ᵉ modèle local (`secondmodel.py`, ex. dolphin non censuré) | **réponses non filtrées** | outil de PAROLE : il répond, n'agit pas ; ne contourne aucune confirmation |
| API locales réseau (Freebox, OPNsense, Starlink, RADIUS) | lecture seule | clés/secrets dans `.env` ; Jarvis observe, ne pilote pas |
| `.env` (secrets) | critique | hors git, jamais envoyé à un service externe |

## Points d'entrée (à tester en priorité)

1. **Bots Telegram / Signal** — l'entrée principale. Auth : un seul ID (Telegram) ou un seul
   numéro (Signal). À tester : usurpation d'expéditeur, messages d'un autre compte, abus des
   commandes (`valide`, `cœur …`), injection de prompt visant à déclencher un outil sensible.
2. **Tableau de bord HTTP** (`dashboard.py`) — par défaut sur `127.0.0.1` (local). Exposable
   au réseau ; dans ce cas un **jeton** est requis (`JARVIS_ECRAN_JETON`). À tester : accès
   sans jeton quand exposé, fuite d'infos (rappels, listes, état maison), 404/401.
3. **Lecture de page web** (`web.py`) — garde-fou **anti-SSRF** : refuse les adresses
   internes (box, Ollama, Home Assistant, métadonnées cloud) et les schémas non http(s).
   À tester : contournement (redirections, DNS rebinding, IPv6, encodages d'IP).
4. **Caméras** (`camera.py`) — ffmpeg restreint à `rtsp/http/https` avec liste blanche de
   protocoles (pas de `file://`). À tester : lecture de fichiers locaux, protocoles exotiques.
5. **Renfort via CLI** (`claude_bridge.py`) — `subprocess` **sans shell**, entrée par stdin,
   clés d'API retirées de l'environnement du sous-processus. À tester : injection d'arguments.
6. **Auto-amélioration** (`growth.py`) — code écrit par l'IA, **jamais appliqué sans ✅**,
   fichiers du cœur interdits. À tester : échappement de l'atelier, écriture hors dossier.
7. **Propositions de cœur** (`core_proposals.py`) — réservé au propriétaire, diff + tests
   isolés + validation obligatoire ; `.env` exclu. À tester : traversée de chemin, application
   sans validation, fichier modifié entre proposition et application (déjà contrôlé).
8. **Domotique / drone** — actions réelles. À tester : déclenchement sans confirmation.
9. **Service lunettes** (`glasses.py`) — serveur HTTP qui reçoit une image à analyser. Jeton
   **exigé** dès que l'hôte n'est pas local (refus de démarrer sinon) ; limite de taille ;
   sonde `/sante` sans jeton. À tester : accès sans jeton, image géante, chemins.
10. **Auth par empreinte vocale** (`voiceprint.py`) — gate les actions sensibles sur la voix
    du propriétaire. **Échoue fermé** (au doute, refus) ; **code maître** de secours à fenêtre
    courte. À tester : rejeu d'un enregistrement de voix, contournement du code, verrouillage
    du propriétaire. Rappel : c'est un FACTEUR (score + seuil), pas un coffre-fort.
11. **API réseau locales** (`freebox.py`, `opnsense.py`, `starlink.py`, `radius.py`,
    `crowdsec.py`) — Jarvis LIT (appareils, journaux de blocage, auth, état uplink) et alerte.
    Jamais d'action offensive. À tester : secrets en clair, confiance aveugle dans les données
    lues (ce sont des données, pas des instructions).

### Réseau — surveiller sans attaquer (ligne tenue)

Toute la couche réseau est **défensive** : CrowdSec (intrusions bloquées), `vulnscan.py`
(audit de posture **non destructif** — détecte une porte ouverte, ne la défonce pas),
`freebox.py` (inconnus sur le Wi-Fi), `wifiwatch.py` (symptôme de déauth ; la protection
reste le **PMF** sur l'AP), `opnsense.py` (fil d'alarme sur la segmentation VLAN),
`starlink.py` (coupure uplink). **Jamais** : écrire/lancer un exploit, pirater un appareil,
déauthentifier, brouiller, « blanchir » une requête pour contourner un filtre. Ces demandes
ont été refusées par conception.

## Protections en place

- **Un seul interlocuteur** autorisé par bot (ID / numéro).
- **Confirmation** du propriétaire pour toute action sensible (le LLM ne peut pas l'outrepasser).
- **Fichiers du cœur protégés** : l'auto-amélioration ne les touche jamais ; modifiables
  seulement via une proposition relue et validée par le propriétaire.
- **Secrets** dans `.env` (hors git) ; `.env.example` vide ; jamais d'e-mail/nom envoyé dehors.
- **Anti-SSRF** (`netguard.py`) sur la lecture de page ; **ffmpeg** sans accès disque.
- **Tableau de bord** : local par défaut, jeton à temps constant si exposé.
- **Validation de noms** (plugins, propositions) et **anti-traversée de chemin**.
- **Rien n'est appliqué sans un humain** : génération → sandbox → tests → ✅.
- **Cybersurveillance continue** (`cyberwatch.py`) : en boucle, la sentinelle machine
  **et** un **tripwire d'intégrité du cœur** (`core_integrity.py`) qui alerte si un fichier
  du cœur est modifié/supprimé hors du circuit validé. Après un changement légitime, le
  propriétaire « rebase » la référence (commande `rebase cœur`). Limite : la référence est
  un fichier local — un attaquant qui modifie le code peut aussi la modifier ; c'est un
  signal précoce, à compléter par des droits de fichiers stricts et un compte dédié.
- **Détection de persistance** (`persistance.py`, branchée dans la cybersurveillance) :
  surveille les mécanismes de **porte dérobée d'après-intrusion** que la sentinelle ne couvre
  pas — clé SSH ajoutée à `authorized_keys`, tâche **cron**, service d'**autostart**, fichier
  de démarrage (`.bashrc`…) modifié. **Lecture seule + alerte** (clé SSH et cron = critiques) ;
  jamais de suppression auto (casserait un accès légitime et une preuve). 1re exécution = l'état
  courant devient la référence silencieuse ; après un ajout légitime, le propriétaire « accepte
  la persistance ». Même limite que le tripwire : la référence est un fichier local.
- **Défense active** (`defense.py`, sur la machine, jamais offensive) : journal horodaté
  des alertes critiques (preuves) et **copie saine du cœur** restaurable si on le trafique
  (`restaure cœur <fichier>`, sur confirmation ; `sauvegarde cœur` pour refaire la référence
  après une install/mise à jour saine). Pas de « hack back » : aucune action contre un tiers.
- **Réaction automatique** (opt-in, `JARVIS_AUTO_RESTAURATION=1`) : sur altération d'un
  fichier du cœur, Jarvis alerte, garde la preuve ET **restaure seul** la version saine
  (réversible). Ligne de sécurité clé : la **génération de code** peut être déclenchée
  automatiquement, mais son **application reste toujours derrière la ✅ du propriétaire** —
  sinon une fausse attaque suffirait à faire exécuter du code non relu.
- **Pot de miel** (`honeypot.py`, opt-in `JARVIS_HONEYPOT=1`) : service leurre qui détecte
  les intrus (toute connexion est suspecte → preuve + alerte). Conçu comme la pièce LA MOINS
  privilégiée : aucun accès au cœur ni à l'exécution de code, délai d'attente et nombre de
  connexions plafonnés (anti-DoS), entrées nettoyées (anti-injection de log). Toute riposte
  active (blocage d'IP) reste défensive et confirmée — jamais de contre-attaque (hack back
  illégal ; l'IP source peut être usurpée, un blocage auto aveugle se retourne contre toi).
- **Blocage d'IP défensif** (`ipblock.py`) : ferme la porte à une IP d'attaquant sur ton
  pare-feu (`bloque <ip>`), **sur ta décision** après une alerte — jamais en automatique
  aveugle (une IP source peut être usurpée). Refuse les IP internes/privées/passerelle et
  une liste blanche (anti auto-DoS). Réversible (`débloque <ip>`). Ce n'est pas une
  contre-attaque : on ne touche jamais à la machine distante.
- ~718 tests automatisés, dont des tests de sécurité dédiés.

## Métadonnées qui sortent de la machine (vie privée)

Jarvis est **local d'abord**. Ce qui quitte la machine, et quand :

| Vers | Quoi | Quand | Couper |
|---|---|---|---|
| Renfort Claude/Gemini | ta question + le contexte (**prénom et ville retirés par défaut**, voir plus bas) | escalade d'une question dure | `JARVIS_HORS_LIGNE=1`, ou le 2ᵉ modèle local |
| Renfort Claude/Gemini (vision) | une **image** (vue drone / caméra / lunettes) | quand tu demandes de décrire une image | pas de vision cloud (`JARVIS_VISION=local`/`0`) |
| Service météo (open-meteo) | ta ville | à chaque météo (inhérent au service) | ne pas utiliser la météo / `JARVIS_HORS_LIGNE=1` |
| Recherche web | ta requête / l'URL (User-Agent **générique**) | quand tu demandes une recherche | anti-SSRF, local brain |
| Messagerie (Telegram / Signal / Matrix) | tes alertes et ton dialogue (texte, voix, clips, snapshots) | selon le canal configuré | Telegram **non chiffré E2E** → préférer Signal/Matrix |
| Webhooks configurés (piscine…) | ce que tu règles | optionnel, vers **tes** endpoints | ne pas configurer |

**Anonymisation du renfort (par défaut, `JARVIS_RENFORT_ANONYME=1`)** : avant tout envoi au
cloud, un point de contrôle unique (`claude_bridge._anonymiser`, appliqué au prompt système,
au prompt mentor et à chaque `ask`) remplace ton **prénom** et ta **ville** par des termes
neutres. Ça tue les fuites **systématiques** ; ça ne peut pas garantir qu'une autre donnée
perso glissée par le modèle local dans la question ne parte pas — pour ça, le mode hors-ligne.

**Ne sort jamais** : ton e-mail (vérifié : aucune occurrence dans le code), les clés/secrets
(seulement vers leur hôte légitime, jamais loggés), le `.env`, et **en mode hors-ligne, rien
du tout**. Les API réseau (Freebox, OPNsense, Starlink, RADIUS, CrowdSec) sont **locales**.
Nuance honnête : une **image** envoyée à la vision cloud ne peut pas être anonymisée (c'est
la fonction même) — elle montre ce qu'elle montre ; coupe la vision cloud si c'est un souci.

## RCE par conception (le risque principal, assumé)

Un plugin est du **code Python exécuté avec les droits de Jarvis**. C'est voulu (c'est ainsi
qu'on ajoute des capacités). La défense est **procédurale** : ne charger que du code relu, et
l'approbation humaine avant activation. Quiconque réussit à faire exécuter du code comme
plugin obtient l'exécution complète. C'est la cible n°1 d'un test : par où du code non relu
pourrait-il entrer et être chargé.

## Limites connues

- **DNS rebinding** : l'anti-SSRF vérifie à la résolution, pas à la connexion. Pour un
  durcissement total, fixer l'IP résolue.
- **Injection de prompt** : une page/un message malveillant peut tenter d'orienter le LLM ;
  la barrière finale reste la confirmation humaine sur les actions sensibles.
- Jarvis a autant de pouvoir que la machine : domotique, drone, fichiers. L'isoler (compte
  dédié, pare-feu, **réseau séparé pour les objets** — cf. `opnsense.py`) réduit l'impact
  d'une compromission. La segmentation VLAN cœur/IoT est la mesure la plus efficace contre
  le maillon faible qu'est l'IoT.
- **2ᵉ modèle local non censuré** (si activé) : ses réponses ne sont pas filtrées et Jarvis
  les relaie. C'est un outil de parole (aucune action) ; le choix de l'activer t'appartient.
- **Auth vocale** : un enregistrement de ta voix (rejeu) peut tromper la reconnaissance.
  Pour le critique, garder un second facteur (code maître / confirmation).

## Signaler une faille

Ne pas ouvrir d'issue publique. Contacter directement le propriétaire du dépôt.
