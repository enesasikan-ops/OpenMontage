"""Ligne de commande du générateur.

    python -m scaffold packs                              # liste les packs de modèles
    python -m scaffold exemple jarvis-capacite > ma.yaml  # config d'exemple d'un pack
    python -m scaffold generer ma.yaml --simuler          # montre ce qui serait créé
    python -m scaffold generer ma.yaml                    # génère
    python -m scaffold generer ma.yaml --update           # régénère en gardant le code manuel
"""

import argparse
import sys
from pathlib import Path

from scaffold.core import Generator, Pack, ScaffoldError, list_packs, load_config

LABELS = {"creer": "+ créer       ", "ignorer": "= ignorer     ", "ecraser": "! écraser     ",
          "mettre_a_jour": "~ mettre à jour", "identique": "· identique   "}


def cmd_packs(_args) -> int:
    for name in list_packs():
        print(f"{name:20} {Pack.load(name).description}")
    return 0


def cmd_exemple(args) -> int:
    pack = Pack.load(args.pack)
    sample = pack.root / "exemple.yaml"
    if not sample.exists():
        raise ScaffoldError(f"Le pack « {args.pack} » ne fournit pas d'exemple.")
    sys.stdout.write(sample.read_text(encoding="utf-8"))
    return 0


def cmd_generer(args) -> int:
    config = load_config(args.config)
    pack = Pack.load(args.pack or config.pop("pack", None) or "jarvis-capacite")
    config.pop("pack", None)
    gen = Generator(pack, Path(args.sortie))
    actions = gen.plan(config, force=args.force, update=args.update)
    root = gen.root
    for a in actions:
        rel = a.path.relative_to(root)
        print(f"{LABELS[a.kind]}  {rel}")
        for w in a.warnings:
            print(f"      ⚠️  {w}")
        if args.diff and a.diff:
            print(a.diff)
    if args.simuler:
        print("\n(simulation : rien n'a été écrit)")
        return 0
    gen.apply(actions)
    written = sum(a.kind in ("creer", "ecraser", "mettre_a_jour") for a in actions)
    print(f"\n✅ {written} fichier(s) écrit(s).")
    for note in pack.notes:
        print(f"→ {note}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scaffold", description="Générateur de code")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("packs", help="liste les packs de modèles").set_defaults(func=cmd_packs)
    p = sub.add_parser("exemple", help="affiche une configuration d'exemple")
    p.add_argument("pack")
    p.set_defaults(func=cmd_exemple)
    g = sub.add_parser("generer", help="génère le code à partir d'une configuration")
    g.add_argument("config", type=Path)
    g.add_argument("--pack", help="pack de modèles (sinon : clé « pack » de la config)")
    g.add_argument("--sortie", default=".", help="dossier racine de sortie (défaut : dossier courant)")
    g.add_argument("--simuler", action="store_true", help="montre le plan sans rien écrire")
    g.add_argument("--diff", action="store_true", help="affiche les différences")
    mode = g.add_mutually_exclusive_group()
    mode.add_argument("--update", action="store_true", help="régénère en gardant les zones manuelles")
    mode.add_argument("--force", action="store_true", help="écrase les fichiers existants")
    g.set_defaults(func=cmd_generer)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ScaffoldError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
