"""The `logger-generator` command line."""
import argparse
import sys

from . import __version__, ems, fridgetag, haier, library, metafridge, scenarios


def _description(module):
    return module.__doc__.strip()


def build_parser():
    parser = argparse.ArgumentParser(
        prog="logger-generator",
        description="Synthetic cold chain logger downloads in the exact formats the devices write, laid out like the logger's USB drive. "
                    "Deterministic: the same arguments and seed give byte-identical files.",
        epilog="Run `logger-generator COMMAND --help` for each command's options and format notes.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--list-scenarios", action="store_true", help="list every scenario and exit")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, module, summary in (
        ("fridgetag", fridgetag, "Berlinger Fridge-tag 2 / 2E / 2L history report (.txt + .pdf)"),
        ("ems", ems, "WHO PQS E006 EMS drive (CURRENT_DATA, SYNC, DATA_HISTORY, 60DTR PDF)"),
        ("haier", haier, "Haier HETL-01 30-day recorder export (HE<serial>.CSV)"),
        ("metafridge", metafridge, "Aucma MetaFridge CFD-50 SDD 30 DTR report (.csv + .pdf)"),
    ):
        sub = commands.add_parser(name, help=summary, description=_description(module),
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
        module.add_arguments(sub)
        sub.set_defaults(run=module.run)
    story = commands.add_parser("scenario", help="a curated multi-file story (see --list-scenarios)",
                                description=_description(scenarios) + "\n\n" + scenarios.catalogue(),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    story.add_argument("name", nargs="?", choices=list(scenarios.STORIES), metavar="NAME",
                       help="one of: " + ", ".join(scenarios.STORIES))
    story.add_argument("--list", action="store_true", help="list every scenario and exit")
    story.add_argument("--out", help="folder to write into (subfolders per drive where the story has several)")
    story.set_defaults(run=_run_story)
    test_library = commands.add_parser("library", help="the test library: curated cases with expected outcomes and a manifest",
                                       description=_description(library),
                                       formatter_class=argparse.RawDescriptionHelpFormatter)
    library.add_arguments(test_library)
    test_library.set_defaults(run=library.run)
    return parser


def _run_story(args):
    if args.list or not args.name:
        print(scenarios.catalogue())
        return
    if not args.out:
        raise SystemExit("logger-generator scenario: --out is required")
    print(scenarios.STORIES[args.name](args.out))


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_scenarios:
        print(scenarios.catalogue())
        return 0
    if not args.command:
        parser.print_help()
        return 2
    args.run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
