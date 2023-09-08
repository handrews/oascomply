import argparse
import json
from pathlib import Path
from typing import (
    Any, Iterator, Mapping, Optional, Sequence, Tuple, Type, Union
)
import logging
import sys

import oascomply
from oascomply.oassource import (
    DirectMapSource, FileMultiSuffixSource, HttpMultiSuffixSource,
)
from oascomply.apidescription import ApiDescription
from oascomply.serializer import OASSerializer
from oascomply.urimapping import (
    URI, URIError, LocationToURI, PathToURI, URLToURI,
)
from oascomply.resource import OASResourceManager


logger = logging.getLogger(__name__)


HELP_PROLOG = """
Load and validate an OpenAPI Description/Definition (OAD).

Explanations of "location specification" and "prefix specification"
are provided after the option list.
"""

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

If either OASTYPE or ADDITIONAL_URIs are provided, the file or network
resource is loaded and parsed up front.  If ADDITIONAL_URIs are provided
without OASTYPE, the OASTYPE is assumed to be OpenAPI.

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


DEFAULT_SUFFIXES = ('.json', '.yaml', '.yml', '')  # TODO: not sure about ''
"""Default suffixes stripped from -f paths and -u URLs"""


def _add_verbose_option(parser):
    parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        help="Increase verbosity; can passed twice for full debug output.",
    )


def _add_strip_suffixes_option(parser):
    parser.add_argument(
        '-x',
        '--strip-suffixes',
        nargs='*',
        default=DEFAULT_SUFFIXES,
        help="For documents loaded with -f or -u without an explict URI "
            "assigned on the command line, assign a URI by stripping any "
            "of the given suffixes from the document's URL; passing this "
            "option without any suffixes disables this behavior, treating "
            "the unmodified URL as the URI; the default stripped suffixes "
            "are .json, .yaml, .yml",
    )


class CustomArgumentParser(argparse.ArgumentParser):
    def _fix_message(self, message):
        # nargs=+ does not support metavar=tuple
        return message.replace(
            'FILES [FILES ...]',
            'FILE [URI] [URI ...] [TYPE]',
        ).replace(
            'DIRECTORIES [DIRECTORIES ...]',
            'DIRECTORY [URI_PREFIX]',
        ).replace(
            'URLS [URLS ...]',
            'URL [URI] [URI ...] [TYPE]',
        ).replace(
            'PREFIXES [PREFIXES ...]',
            'URL_PREFIX [URI_PREFIX]',
        )

    def format_usage(self):
        return self._fix_message(super().format_usage())

    def format_help(self):
        return self._fix_message(super().format_help())


class ActionAppendLocationToURI(argparse.Action):
    @classmethod
    def make_action(
        cls,
        arg_cls: Type[LocationToURI] = LocationToURI,
        strip_suffixes: Sequence[str] = (),
    ):
        logger.debug(f'Registering {arg_cls.__name__} argument action')
        return lambda *args, **kwargs: cls(
            *args,
            arg_cls=arg_cls,
            strip_suffixes=strip_suffixes,
            **kwargs,
        )

    def __init__(
        self,
        option_strings: str,
        dest: str,
        *,
        nargs: Optional[str] = None,
        arg_cls: Type[LocationToURI],
        strip_suffixes: Sequence[str],
        **kwargs
    ) -> None:
        if nargs != '+':
            raise ValueError(
                f'{type(self).__name__}: expected nargs="+"'
            )
        self._arg_cls = arg_cls
        self._strip_suffixes = strip_suffixes
        super().__init__(option_strings, dest, nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        # This should do initial classification into locations, URIs,
        # and OASTypes.
        #
        # The first value is always a location (path or URL), the last
        # MAY be an OASType, and all others are URI (not URI-references).
        # URIs always have at least one ":" in them, and OASTypes never
        # include a ":", so this is a fast way to distinguish them.
        logger.debug(f'Examining {values!r} for {self._arg_cls.__name__}')

        location = values[0]
        oastype = None
        primary_uri = None
        additional_uris = []
        if len(values) > 1:
            if ':' not in values[-1]:
                oastype = values[-1]
                uris = values[1:-1]
            else:
                uris = values[1:]

            if uris:
                primary_uri = uris[0]
                additional_uris = uris[1:]

        arg_list = getattr(namespace, self.dest)
        arg_list.append(
            self._arg_cls(
                location,
                primary_uri,
                additional_uris=additional_uris,
                strip_suffixes=self._strip_suffixes,
                oastype=oastype,
            ),
        )


def parse_logging(args) -> Sequence[str]:
    """
    Parse logging options and configure logging before parsing everything else.

    Without doing this first, we lose valuable logging from the custom arg
    handling classes.  Note that the options are re-added to the main parsing
    pass so that they appear in the help output.
    """
    verbosity_parser = argparse.ArgumentParser(add_help=False)
    _add_verbose_option(verbosity_parser)
    v_args, remaining_args = verbosity_parser.parse_known_args(args)

    oascomply_logger = logging.getLogger('oascomply')
    if v_args.verbose:
        if v_args.verbose == 1:
            oascomply_logger.setLevel(logging.INFO)
        else:
            oascomply_logger.setLevel(logging.DEBUG)
    else:
        oascomply_logger.setLevel(logging.WARNING)
    return remaining_args


def parse_non_logging(remaining_args: Sequence[str]) -> argparse.Namespace:
    """
    Parse everything except for logging and return the resulting namespace.
    """

    # First parse out the strip suffixes option because it is used
    # to configure how other args are parsed.
    strip_suffixes_parser = argparse.ArgumentParser(add_help=False)
    _add_strip_suffixes_option(strip_suffixes_parser)
    ss_args, remaining_args = strip_suffixes_parser.parse_known_args(
        remaining_args,
    )

    parser = CustomArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=HELP_PROLOG,
        epilog=HELP_EPILOG,
        fromfile_prefix_chars='@',
    )
    # Already parsed, but add to include in usage message
    _add_verbose_option(parser)
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
    _add_strip_suffixes_option(parser)
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
