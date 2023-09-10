import sys
import argparse
from pathlib import Path
import json

import yaml


YAML_TO_JASON_DESCRIPTION = """
Convert a YAML file to a JSON file, as JSON is much faster to process.

Note that error handling is minimal, and output files are overwritten
if present.
"""


def yaml_to_json():
    """Entry point for the ``yaml-to-json`` command-line utility."""
    parser = argparse.ArgumentParser(
        description=YAML_TO_JASON_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'infile',
        nargs='+',
        help='YAML files to convert'
    )
    parser.add_argument(
        '-o',
        '--outfile',
    )
    parser.add_argument(
        '-n',
        '--indent',
        type=int,
        default=2,
        help='Indentation level: 0 for newlines without indenting, '
             '-1 for no whitespace of any kind',
    )
    args = parser.parse_args()

    infiles = [Path(i) for i in args.infile]
    if len(infiles) > 1 and args.outfile:
        sys.stderr.write(
            'Cannot specify --output-file with multiple input files\n'
        )
        sys.exit(-1)
    elif args.outfile:
        outfiles = [Path(args.outfile)]
    else:
        outfiles = [i.with_suffix('.json') for i in infiles]

    kwargs = {
        'ensure_ascii': False,
        'indent': args.indent if args.indent >=0 else None,
    }
    if args.indent < 0:
        kwargs['separators'] = (',', ':')

    for index, infile in enumerate(infiles):
        with infile.open() as in_fd, outfiles[index].open(
            'w', encoding='utf-8'
        ) as out_fd:
            json.dump(yaml.safe_load(in_fd), out_fd, **kwargs)
