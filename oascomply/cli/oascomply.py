import argparse
import json
from typing import Sequence
import logging
import sys

import oascomply
from oascomply.apidescription import ApiDescription
from oascomply.serializer import OASSerializer
from oascomply.urimapping import PathToURI, URLToURI
from oascomply.resource import OASResourceManager
from oascomply.cli import (
    DEFAULT_SUFFIXES,
    add_verbose_option,
    add_strip_suffixes_option,
    LocationToURIArgumentParser,
    ActionAppendLocationToURI,
    parse_logging,
)


logger = logging.getLogger(__name__)


HELP_PROLOG = """
Load and validate an OpenAPI Description/Definition (OAD).

Explanations of "location specification" and "prefix specification"
from the option descriptions below are provided after the option list.
"""

# TODO: When parsing up front due to OASType, should references only
#       be followed if reached from the root document?  Probably yes.

HELP_EPILOG = """
Each file or network resource in an OAD has both a URL (the lcoation
from which it is loaded) and a URI (the identifier with which it can
be referenced using "$ref" or similar keywords).  By default, the URI
is the same as the URL, with local files being assigned the corresponding
"file:" URL.

LOCATION SPECIFICATIONS
=======================

The -f (--file) and -u (--url) options take a location specification,
where several arguments can follow the option with the following syntax:

   LOCATION [URI [ADDITIONAL_URI ...]] [OASTYPE]

The syntax for the location is specific to each option.  If the URI
is not provided, one is generated from the URL, taking into account
the -x (--strip-suffixes) option.

ADDITIONAL_URIs can be passed if the contents of the file define URIs
other than the URI that is used for the entire file.

The OASTYPE is the semantic type of the entire file, as taken from
the section headers in the OAS itself (e.g. OpenAPI, Schema, PathItem, etc.).
If an OASTYPE is provided, the file or network resource is loaded and
parsed prior to resolving any references.

PREFIX SPECIFICATIONS
=====================

The -d (--directory) and -p (--url-prefix) optinos take a prefix specification,
which is a simplified location specification where the URI's path must end with
a "/" to indicate a directory to search:

    LOCATION [URI]

When a reference matches the URI prefix, the remaining URI path is appended
to the location to find the appropriet file or network resource.

If the URI is omitted, the location is converted to a URL (if necessary, such
as with a local directory to a "file:" URL) which is searched directly.

The -D (--directory-suffixes) and -P (--url-suffixes) options control whether
and in what order suffixes are attached to the requested URI to find its
URL under the location.

INITIAL (a.k.a. ROOT) DOCUMENT
==============================

The initial OAD document is parsed immediately, with other documents
either loaded up front or parsed as they are referenced, as noted abvoe.
Each document that makes up
and OAD has a URL (the location from which it was loaded) and a URI
(the identifier used to reference it in "$ref" and similar keywords).

The initial document is the first of:

1. The document from -i (--initial-resource), which takes a URI (not URL)
2. The first document from a -f (--file) containing an "openapi" field
3. The first document from a -u (--url) containing an "openapi" field

VALIDATION AND LINTING
======================

Currently, the only option relating to validation and linting is the
-e (--examples) option, which can be used to disable validation of
"example", "examples", and "default" by the relevant Schema Object(s).

OUTPUT
======

oascomply parses OADs into an RDF graph, which can be written to stdout
by passing the -o (--output-format) option.  Without an argument, the
output is written in N-Triples 1.1 format, in utf-8 encoding.  Other
formats supported by Python's rdflib can be passed as arguments.

A non-RDF serialization intended for human-readability can be written out
using "-o toml"; this is an experimental format intended for casual
debugging rather than machine processing.  It shortens the URIs in the graph
in ways that RDF serializations do not allow.

The -n (--number-lines) option can be passed to include line numbers in
the error or graph output.  This option is expensive, particularly with
YAML, so it is disabled by default.

TUTORIAL
========

See the "Loading OADs and Schemas" tutorial for full documentation of
the OAD-loading options described above and how they support various
known use cases.
"""


def parse_non_logging(remaining_args: Sequence[str]) -> argparse.Namespace:
    """
    Parse everything except for logging and return the resulting namespace.
    """

    # First parse out the strip suffixes option because it is used
    # to configure how other args are parsed.
    strip_suffixes_parser = argparse.ArgumentParser(add_help=False)
    add_strip_suffixes_option(strip_suffixes_parser)
    ss_args, remaining_args = strip_suffixes_parser.parse_known_args(
        remaining_args,
    )

    parser = LocationToURIArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=HELP_PROLOG,
        epilog=HELP_EPILOG,
        fromfile_prefix_chars='@',
    )
    # Already parsed, but add to include in usage message
    add_verbose_option(parser)
    parser.add_argument(
        '-i',
        '--initial',
        help="The URI of the document from which to start validating.",
    )
    parser.add_argument(
        '-f',
        '--file',
        nargs='+',
        action=ActionAppendLocationToURI.make_action(
            arg_cls=PathToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        default=[],
        dest='files',
        help="A location specification using a filesytem path as the location.",
    )
    parser.add_argument(
        '-u',
        '--url',
        nargs='+',
        action=ActionAppendLocationToURI.make_action(
            arg_cls=URLToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        default=[],
        dest='urls',
        help="A location specification using a URL for the location; "
             "currently only 'http:' and 'https:' URLs are supported.",
    )
    # Already parsed, but add to include in usage message
    add_strip_suffixes_option(parser)
    parser.add_argument(
        '-d',
        '--directory',
        nargs='+',
        action=ActionAppendLocationToURI.make_action(arg_cls=PathToURI),
        default=[],
        dest='directories',
        help="A prefix specification using a local directory as the location.",
    )
    parser.add_argument(
        '-p',
        '--url-prefix',
        nargs='+',
        action=ActionAppendLocationToURI.make_action(arg_cls=URLToURI),
        default=[],
        dest='url_prefixes',
        help='A prefix specification using a URL (with a path ending in "/") '
             "for the location; only 'http:' and 'https:' URLs are supported.",
    )
    parser.add_argument(
        '-D',
        '--directory-suffixes',
        nargs='*',
        default=('.json', '.yaml', '.yml'),
        dest='dir_suffixes',
        help="The list of suffixes to search, in order, when resolving using "
             "any directory prefix specification; files that do not fit the "
             "suffix pattern of the directory should be loaded with -f.",
    )
    parser.add_argument(
        '-P',
        '--url-prefix-suffixes',
        nargs='*',
        default=(),
        dest='url_suffixes',
        help="The list of suffixes to search, in order, when resolving using "
             "any URL prefix specification; resources that do not fit the "
             "suffix pattern of the URL prefix should be loaded with -u.",
    )
    parser.add_argument(
        '-n',
        '--number-lines',
        action='store_true',
        help="Enable line and column numbers in the graph and in "
             "error reporting; this has a considerable performance "
             "impact, especially for YAML",
    )
    parser.add_argument(
        '-e',
        '--examples',
        choices=('true', 'false'),
        default='true',
        help="Pass 'false' to disable validation of examples and defaults "
             "by the corresponding schema.",
    )
    parser.add_argument(
        '-o',
        '--output-format',
        nargs='?',
        const='nt11',
        metavar="nt | ttl | n3 | trig | json-ld | xml | hext | ...",
        help="Serialize the parsed graph to stdout in the given format, "
             "or 'nt11' (N-Triples with UTF-8 encoding) if no format name "
             "is provided.  Format names are passed through to rdflib, "
             "see that library's documentation for the full list of "
             "options.",
    )
    parser.add_argument(
        '-O',
        '--output-file',
        help="NOT YET IMPLEMENTED "
             "Write the output to the given file instead of stdout",
    )
    parser.add_argument(
        '--test-mode',
        action='store_true',
        help="Omit data such as 'locatedAt' that will change for "
             "every environment and produce sorted nt11 output.  "
             "This is intended to facilitate "
             "automated testing of the entire system.",
    )

    args = parser.parse_args(remaining_args)

    logger.debug(f'Processed arguments:\n{args}')

    # TODO: This does not seem to work at all - fix or toss?
    # Note that if -P or -D are actually passed with
    # the args matching the default, this check will
    # still work as they will be set as a list instead
    # of the default values which are tuples
    for attr, opt, check in (
        ('initial', '-i', lambda arg: True),
        ('urls', '-u', lambda arg: True),
        ('url_prefixes', '-p', lambda arg: True),
        ('dir_suffixes', '-D', lambda arg: arg == (
            '.json', '.yaml', '.yml',
        )),
        ('url_suffixes', '-P', lambda arg: arg == ()),
        ('output_file', '-O', lambda arg: True),
    ):
        if hasattr(args, attr) and not check(getattr(args, attr)):
            raise NotImplementedError(f'{opt} option not yet implemented!')

    return args


def load(initial_args=sys.argv[1:]):
    remaining_args = parse_logging(initial_args)
    args = parse_non_logging(remaining_args)
    manager = OASResourceManager(
        oascomply.catalog,
        files=args.files,
        urls=args.urls,
        directories=args.directories,
        url_prefixes=args.url_prefixes,
        dir_suffixes=args.dir_suffixes,
        url_suffixes=args.url_suffixes,
    )

    entry_resource = manager.get_entry_resource(
        args.initial,
    )

    desc = None
    errors = []

    if entry_resource is None:
        errors.append({
            'error': 'ERROR: '
                'oascomply requires either -i (--initial-resource) along with '
                'at least one of -d (--directory) or -p (--url-prefix). OR at '
                'least one of -f (--file) or -u (--url)\n',
            'stage': 'configuration',
        })
        return desc, errors, args

    if 'openapi' not in entry_resource:
        errors.append({
            'error': 'ERROR: The initial document must contain "openapi"\n',
            'stage': 'configuration',
        })
        return desc, errors, args

    desc = ApiDescription(
        entry_resource,
        resource_manager=manager,
        test_mode=args.test_mode,
    )

    errors.extend(desc.validate(
        validate_examples=(args.examples == 'true'),
    ))
    if errors:
        return desc, errors, args

    errors.extend(desc.validate_graph())
    return desc, errors, args


def report_errors(errors):
    for err in errors:
        logger.critical(
            f'Error during stage "{err["stage"]}"' +
            (
                f', location <{err["location"]}>:'
                if err.get('location', 'TODO') != 'TODO'
                else ':'
            )
        )
        logger.critical(json.dumps(err['error'], indent=2))

def run():
    desc, errors, args = load()

    if errors:
        report_errors(errors)
        sys.stderr.write('\nAPI description contains errors\n\n')
        sys.exit(-1)

    if args.output_format is not None or args.test_mode is True:
        serializer = OASSerializer(
            output_format=args.output_format,
            test_mode=args.test_mode,
        )
        serializer.serialize(
            desc.get_oas_graph(),
            base_uri=str(desc.base_uri),
            resource_order=[str(v) for v in desc.validated_resources],
        )

    sys.stderr.write('Your API description is valid!\n')
