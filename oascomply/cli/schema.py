import sys
import argparse
import json

import yaml
from jschon import JSON, JSONSchema, URI

from oascomply.oas3dialect import (
    OAS30_DIALECT_METASCHEMA,
    OAS30_EXTENSION_VOCAB,
    OAS31_DIALECT_METASCHEMA,
    OAS31_EXTENSION_VOCAB,
)

DESCRIPTION = """
Evaluates the instance against the schema using the jschon library.

The standard 2020-12 vocabularies as well as the OAS 3.0 and 3.1
extension vocabularies are supported, using the following URIs for
the OAS extensions:

3.0:  {OAS30_EXTENSION_VOCAB}
3.1:  {OAS31_EXTENSION_VOCAB}

The 2020-12 format-assertion vocabulary is also supported, although
currently not all formats are fully supported.  The OAS 3.0 dialect
is loaded with the format-assertion vocabulary enabled.

The metaschema (and dialect) is deterined as follows:

1.  "$schema" is respected if present
2.  A metaschema passed on the command line, if present
3.  The OAS 3.0 dialect <{OAS30_DIALECT_METASCHEMA}> is used by default

The OAS 3.1 dialect <{OAS31_DIALECT_METASCHEMA}> is also supported.
"""


def evaluate():
    parser = argparse.ArgumentParser(
        description=DESCRIPTION,
        epilog=f'Note that the schema "{OAS30_DIALECT_METASCHEMA}" is '
                '*NOT* provided by the OpenAPI Initiative, but is part of the '
                'oascomply package (oascomply.schemas/oas/v3.0/base.json)',
        fromfile_prefix_chars='@',
    )
    parser.add_argument(
        'instance',
        help='The JSON or YAML file to validate',
    )
    parser.add_argument(
        'schema',
        help='The schema, in JSON or YAML format, to use',
    )
    parser.add_argument(
        '-r',
        '--referenced-schema',
        action='append',
        dest='refs',
        default=[],
        help='NOT YET SUPPORTED! '
             'An additional schema from which to resolve references; '
             'can be passed multiple times; note that schema documents '
             'that reference each other are not currently supported; '
             'currently, if schema A references schema B, then schema B '
             'must be passed with -r *BEFORE* schema A',
    )

    meta_group = parser.add_mutually_exclusive_group()
    meta_group.add_argument(
        '-m',
        '--metaschema',
        help='The metaschema URI to use if "$schema" is not present; '
             'any metaschema that only requires known vocabularies '
             'can be used',
    )
    meta_group.add_argument(
        '-d',
        '--dialect',
        choices=('2020-12', 'oas30', 'oas31'),
        default='oas30',
        help='Choose a pre-defined dialect as the default metaschema to use'
             'if "$schema" is not present.',
    )
    parser.add_argument(
        '-o',
        '--output',
        choices=('basic', 'detailed', 'verbose'),
        nargs='?',
        const='basic',
        help='On success, print the annotation output to stdout using '
             'the given standard format; the default annotation format '
             "is 'basic'",
    )
    parser.add_argument(
        '-e',
        '--error-format',
        choices=('basic', 'detailed', 'verbose'),
        default='detailed',
        help='Set the output format to use for error reporting; the '
             "default format is 'detailed'",
    )

    args = parser.parse_args()
    metaschema_uri = URI(OAS30_DIALECT_METASCHEMA)
    metaschema_errors = {}

    # TODO: Actually detect and parse json properly
    sys.stderr.write(f'Loading instance {args.instance}...\n')
    with open(args.instance) as inst_fd:
        instance = JSON(yaml.safe_load(inst_fd))

    # TODO: Be more forgiving about the load order of refschemas,
    #       as this means that a schema can only a reference another
    #       schema that has already been loaded
    for ref in args.refs:
        # Constructing a JSONSchema registers it with the Catalog
        sys.stderr.write(f'Loading ref schema {ref}...\n')
        with open(ref) as ref_fd:
            ref_schema = JSONSchema(
                yaml.safe_load(ref_fd),
                metaschema_uri=metaschema_uri,
                catalog='oascomply',
            )
            meta_result = ref_schema.validate()
            if not meta_result.valid:
                metaschema_errors[ref] = meta_result

    sys.stderr.write(f'Loading schema {args.schema}...\n')
    with open(args.schema) as schema_fd:
        schema = JSONSchema(
            yaml.safe_load(schema_fd),
            metaschema_uri=metaschema_uri,
            catalog='oascomply',
        )
        meta_result = schema.validate()
        if not meta_result.valid:
            metaschema_errors[args.schema] = meta_result

    if metaschema_errors:
        for path, meta_result in metaschema_errors.items():
            sys.stderr.write(
                f'OAS 3.0 metaschema validation failed for {args.schema}!\n',
            )
            json.dump(
                meta_result.output(args.error_format),
                sys.stderr,
                indent=2,
            )
            sys.stderr.write('\n\n')
        sys.exit(-1)

    sys.stderr.write('Evaluating the instance against the schema...\n')
    result = schema.evaluate(instance)
    if result.valid:
        sys.stderr.write('Your instance is valid!\n')
        if args.output:
            json.dump(result.output(args.output), sys.stdout, indent=2)
            sys.stdout.write('\n')
    else:
        sys.stderr.write('Schema validation failed!\n')
        json.dump(result.output(args.error_format), sys.stderr, indent=2)
        sys.stderr.write('\n')
