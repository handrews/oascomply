import sys
import argparse
import logging
import json
from typing import Mapping, Sequence

import yaml
import toml
from jschon import JSONSchema
from jschon.resource import JSONResource

import oascomply
from oascomply.oas3dialect import (
    OAS30_DIALECT_METASCHEMA,
    OAS30_EXTENSION_VOCAB,
    OAS31_DIALECT_METASCHEMA,
    OAS31_EXTENSION_VOCAB,
)
from oascomply.urimapping import URI, LocationToURI, PathToURI, URLToURI
from oascomply.cli import (
    parse_logging,
    add_verbose_option,
    add_strip_suffixes_option,
    ActionAppendLocationToURI,
    ActionStoreLocationToURI,
    LocationToURIArgumentParser,
)
from oascomply.resource import OASResourceManager


logger = logging.getLogger(__name__)


STRIP_SUFFIXES_OPTS = '--local-* or --http-*'


DESCRIPTION = f"""
Evaluates the instance with the schema using the jschon library.
If no instance is provided the schema is evaluated by its metaschema.

Schemas and instances can be in either JSON or YAML format.

The standard 2020-12 vocabularies as well as the OAS 3.0 and 3.1
extension vocabularies are supported, using the following URIs for
the OAS extensions:

3.0:  <{OAS30_EXTENSION_VOCAB}>
3.1:  <{OAS31_EXTENSION_VOCAB}>

The 2020-12 format-assertion vocabulary is also supported, although
currently not all formats are fully supported.  The OAS 3.0 dialect
is loaded with the format-assertion vocabulary enabled.

The metaschema (and dialect) is deterined as follows:

1.  "$schema" is respected if present
2.  A metaschema passed on the command line, if present
3.  The OAS 3.0 dialect <{OAS30_DIALECT_METASCHEMA}>
    is used by default

The OAS 3.1 dialect <{OAS31_DIALECT_METASCHEMA}>
is also supported.

Explanations of "location specification" and "prefix specification"
from the option descriptios below are provided after the option list.
"""


EPILOG = f"""
Each schema file or network resource has both a URL (the location from
which it was actually loaded) and a URI (which is used for resolving
"$ref" and "$dynamicRef").

The URI is set by the "$id" keyword in the root schema object, if one
is present.  If it is absent or relative in a standalone schema file,
the request URI is the initial base URI (if relative) or the entire
URI (if absent).

By default, the URI is simply the URL (which for local files is simply
the equivalent 'file:' URL), but an alternate request URI can be
provided as a second argument after the schema file or URL.

This is used to simulate retrieving a schema from (for example)
its production location, while actually loading it from your local
source control or from a test HTTP server.

If a schema is known to contain subschemas with a "$id", the URIs
defined by those "$id"s can be provided as additional URIs on the
command line to let oasschema know which file or network resource
to load to find the URIs.  This is only necessary if the file or
network resource is not loaded for some other reason prior to
referencing the subschema "$id"s.

All of this is managed with location and/or prefix specifications.

LOCATION SPECIFICATIONS
=======================

Options for specifying schema files or resources individually take
a location specification, where several arguments can follow the option
with the following syntax:

   LOCATION [URI [ADDITIONAL_URI ...]] [OASTYPE]

For the location, Lower-case short options (long options beginning
with --local) take a filesystem path, while upper-case short options
(long options beginning with --http) take an 'http:' or 'https:' URL.

This style is used to set the schema where evaluation begins (-s, -S)
and the metaschema (-m, -M) and any individual schemas that might be
referenced by the evaluating schema and/or the metaschema (-r, -R).

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

The OAS 3.0 dialect metaschema
==============================

Note that the schema "{OAS30_DIALECT_METASCHEMA}" is 
*NOT* provided by the OpenAPI Initiative, but is part of the
oascomply package (oascomply.schemas/oas/v3.0/base.json)
"""


def parse_args(initial_args=sys.argv[1:]):
    remaining_args = parse_logging(initial_args)
    return parse_non_logging(remaining_args)


def parse_non_logging(remaining_args: Sequence[str]) -> argparse.Namespace:
    # First parse out the strip suffixes option because it is used
    # to configure how other args are parsed.
    strip_suffixes_parser = argparse.ArgumentParser(add_help=False)
    add_strip_suffixes_option(
        strip_suffixes_parser,
        relevant_options=STRIP_SUFFIXES_OPTS,
    )
    ss_args, remaining_args = strip_suffixes_parser.parse_known_args(
        remaining_args,
    )

    parser = LocationToURIArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=DESCRIPTION,
        epilog=EPILOG,
        fromfile_prefix_chars='@',
    )

    # Already parsed, but add to include in usage message
    add_verbose_option(parser)

    instance_group = parser.add_mutually_exclusive_group()
    instance_group.add_argument(
        '-i',
        '--local-instance',
        action=ActionStoreLocationToURI.make_action(
            arg_cls=PathToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        help='A file location specification for the instance to evaluate',
    )
    instance_group.add_argument(
        '-I',
        '--http-instance',
        action=ActionStoreLocationToURI.make_action(
            arg_cls=URLToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        help='An HTTP location specification for the instance to evaluate',
    )

    schema_group = parser.add_mutually_exclusive_group()
    schema_group.add_argument(
        '-s',
        '--local-schema',
        action=ActionStoreLocationToURI.make_action(
            arg_cls=PathToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        help='A file location specification for the evaluating schema',
    )
    schema_group.add_argument(
        '-S',
        '--http-schema',
        action=ActionStoreLocationToURI.make_action(
            arg_cls=URLToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        help='An HTTP location specificatoin for the evaulating schema',
    )

    meta_group = parser.add_mutually_exclusive_group()
    meta_group.add_argument(
        '-m',
        '--local-metaschema',
        action=ActionStoreLocationToURI.make_action(
            arg_cls=PathToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        help='A file location specification for the metaschema to use '
             'when "$schema" is absent',
    )
    meta_group.add_argument(
        '-M',
        '--http-metaschema',
        action=ActionStoreLocationToURI.make_action(
            arg_cls=URLToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        help='An HTTP location specification for the metaschema to use '
             'when "$schema" is absent',
    )
    meta_group.add_argument(
        '-t',
        '--dialect',
        choices=('2020-12', 'oas30', 'oas31'),
        default='oas30',
        help='A pre-defined dialect to use as the default metaschema '
             'when "$schema" is not present; oasschema is packaged with the '
             'necessary metaschemas for these dialects',
    )

    parser.add_argument(
        '-r',
        '--local-ref-schema',
        nargs='+',
        action=ActionAppendLocationToURI.make_action(
            arg_cls=PathToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        default=[],
        dest='local_ref_schemas',
        help='A file location specification for a schema referenced through '
             'the evaluating schema and/or metaschema',
    )
    parser.add_argument(
        '-R',
        '--http-ref-schema',
        nargs='+',
        action=ActionAppendLocationToURI.make_action(
            arg_cls=URLToURI,
            strip_suffixes=ss_args.strip_suffixes,
        ),
        default=[],
        dest='http_ref_schemas',
        help='An http location specification for a schema referenced through '
             'the evaluating schema and/or metaschema',
    )

    # Already parsed, but add to include in usage message
    add_strip_suffixes_option(
        parser,
        relevant_options=STRIP_SUFFIXES_OPTS,
    )
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
             "suffix pattern of the directory should be loaded with -r.",
    )
    parser.add_argument(
        '-P',
        '--url-prefix-suffixes',
        nargs='*',
        default=(),
        dest='url_suffixes',
        help="The list of suffixes to search, in order, when resolving using "
             "any URL prefix specification; resources that do not fit the "
             "suffix pattern of the URL prefix should be loaded with -R.",
    )

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument(
        '-a',
        '--annotation=s',
        nargs='+',
        default=[],
        dest='annotations',
        help='One or more annotations to be collected and returned '
             'using the "basic" output format; currently only the '
             '"basic" format is supported with this option, so this.'
             'option cannot be combined with -o',
    )
    output_group.add_argument(
        '-o',
        '--output',
        choices=('basic', 'detailed', 'verbose'),
        nargs='?',
        const='basic',
        help='On success, print the annotation output to stdout using '
             'the given standard format; -o without any argument uses '
             'the "basic" format; this option cannot be combined with -a',
    )

    parser.add_argument(
        '-f',
        '--output-format',
        choices=('json', 'yaml', 'toml'),
        default='json',
        help='The serialization format for output',
    )
    parser.add_argument(
        '-e',
        '--error-format',
        choices=('basic', 'detailed', 'verbose'),
        default='detailed',
        help='Set the output format to use for error reporting; the '
             "default format is 'detailed'",
    )

    parser.add_argument(
        '-C',
        '--dump-catalog',
        action='store_true',
        help='Diagnostic option to show the initial loaded schemas and '
             'metaschemas',
    )
    args = parser.parse_args()

    args = parser.parse_args(remaining_args)

    logger.debug(f'Processed arguments:\n{args}')
    return args


def evaluate(args):
    instance_spec = None
    schema_spec = None
    metaschema_spec = None

    files = []
    if args.local_instance:
        files.append(args.local_instance)
        instance_spec = args.local_instance
    if args.local_schema:
        files.append(args.local_schema)
        schema_spec = args.local_schema
    if args.local_metaschema:
        files.append(args.local_metaschema)
        metaschema_spec = args.local_metaschema
    files.extend(args.local_ref_schemas)

    urls = []
    if args.http_instance:
        urls.append(args.http_instance)
        instance_spec = args.http_instance
    if args.http_schema:
        urls.append(args.http_schema)
        schema_spec = args.http_schema
    if args.http_metaschema:
        urls.append(args.http_metaschema)
        metaschema_spec = args.http_metaschema
    urls.extend(args.http_ref_schemas)

    manager = OASResourceManager(
        oascomply.catalog,
        files=files,
        urls=urls,
        directories=args.directories,
        url_prefixes=args.url_prefixes,
        dir_suffixes=args.dir_suffixes,
        url_suffixes=args.url_suffixes,
    )

    if instance_spec is not None:
        instance = oascomply.catalog.get_resource(
            instance_spec.uri,
            cls=JSONResource,
        )
    else:
        instance = None

    schema = oascomply.catalog.get_schema(
            schema_spec.uri,
            metaschema_uri=
                None if metaschema_spec is None else metaschema_spec.uri,
    )

    if args.dump_catalog:
        yaml.dump(
            manager.get_debug_configuration(),
            stream=sys.stdout,
            indent=2,
            allow_unicode=True,
            sort_keys=False,
        )
        print(flush=True)
        # TODO: don't sys.exit() from anywhere but run()?
        sys.exit()

    oascomply.catalog.resolve_references()

    result = (
        schema.validate() if instance is None
        else schema.evaluate(instance)
    )
    output_format = args.output if result.valid else args.error_format

    return (
        result,
        output_format,
    )


import pygments
import pygments.lexers
import pygments.formatters
OUTPUT_FORMAT_LEXERS = {
    'json': pygments.lexers.JsonLexer,
    'yaml': pygments.lexers.YamlLexer,
    'toml': pygments.lexers.TOMLLexer,
}
def colorize(
    data: str,
    fmt: str,
    style: str = 'solarized-dark',
) -> str:
    if (lexer_cls := OUTPUT_FORMAT_LEXERS.get(fmt)) is not None:
        data = pygments.highlight(
            data,
            lexer=lexer_cls(),
            formatter=pygments.formatters.Terminal256Formatter(
                style=style,
            ),
        )
    return data


def print_output(output, fmt='json'):
    if fmt == 'json':
        data = json.dumps(output, indent=2, ensure_ascii=False)
    elif fmt == 'yaml':
        data = yaml.dump(output, indent=2, allow_unicode=True, sort_keys=False)
    elif fmt == 'toml':
        data = toml.dumps(output)
    print(colorize(data, fmt=fmt))


def run():
    args = parse_args()

    result, output_format = evaluate(args)

    if not result.valid:
        print_output(result.output(output_format))
        print('\nValidation failed!', file=sys.stderr)
        sys.exit(-1)

    if args.annotations:
        print_output(
            result.output('basic', annotations=args.annotations),
            fmt=args.output_format,
        )
    elif output_format is not None:
        print_output(
            result.output(output_format),
            fmt=args.output_format,
        )
    print('Validation successful!', file=sys.stderr)
