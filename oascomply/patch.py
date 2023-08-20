import sys
import argparse
import json
import subprocess
from collections import OrderedDict
from io import StringIO
from pathlib import Path
from typing import Mapping, Sequence, Union

import yaml
import json_merge_patch
from jschon import JSONSchema
from jschon.vocabulary import Metaschema
from jschon.jsonpatch import JSONPatch

from oascomply.oascatalog import OASCatalog

__all__ = [
    'PATCHED_OAS30_SCHEMA_DIR',
    'PATCHED_OAS30_SCHEMA_PATH',
    'PATCHED_OAS31_SCHEMA_DIR',
    'PATCHED_OAS31_SCHEMA_PATH',
    'PATCHED_OAS31_DIALECT_PATH',
    'PATCHED_OAS31_META_PATH',
]


REPO_ROOT = (Path(__file__).parent / '..' ).resolve()

OAS_SCHEMA_DIR = \
    REPO_ROOT / 'submodules' / 'OpenAPI-Specification' / 'schemas'
OAS_V30_SCHEMA = OAS_SCHEMA_DIR / 'v3.0' / 'schema.json'
OAS_V31_SCHEMA = OAS_SCHEMA_DIR / 'v3.1' / 'schema.json'
OAS_V31_SCHEMA_OBJ_DEFAULT_DIALECT = OAS_SCHEMA_DIR / 'v3.1' / 'dialect' / 'base.schema.json'
OAS_V31_SCHEMA_OBJ_EXTENSION_META  = OAS_SCHEMA_DIR / 'v3.1' / 'meta' / 'base.schema.json'

COMPLIANCE_SCHEMA_DIR = REPO_ROOT / 'schemas'
COMPLIANCE_DIALECT_METASCHEMA = \
    COMPLIANCE_SCHEMA_DIR / 'dialect' / 'oas-ontology.json'
COMPLIANCE_VOCAB_METASCHEMA = \
    COMPLIANCE_SCHEMA_DIR / 'meta' / 'oas-ontology.json'

PATCHED_OAS30_SCHEMA_DIR = COMPLIANCE_SCHEMA_DIR / 'oas' / 'v3.0'
PATCHED_OAS30_SCHEMA_PATH = PATCHED_OAS30_SCHEMA_DIR / 'schema.json'

PATCHED_OAS31_SCHEMA_DIR = COMPLIANCE_SCHEMA_DIR / 'oas' / 'v3.1'
PATCHED_OAS31_SCHEMA_PATH = PATCHED_OAS31_SCHEMA_DIR / 'schema.json'
PATCHED_OAS31_DIALECT_PATH = PATCHED_OAS31_SCHEMA_DIR / 'dialect.json'
PATCHED_OAS31_META_PATH = PATCHED_OAS31_SCHEMA_DIR / 'meta.json'

OAS_PATCH_DIR = REPO_ROOT / 'patches' / 'oas'
PATCHES = {
    '3.0': {
        OAS_V30_SCHEMA: {
            'alterschema': {'from': 'draft4', 'to': '2020-12'},
            'patches': [
                OAS_PATCH_DIR / 'v3.0' / 'preliminary-patch.json',
                OAS_PATCH_DIR / 'v3.0' / 'merge-patch.yaml',
            ],
            'outfile': PATCHED_OAS30_SCHEMA_PATH,
        },
    },
    '3.1': {
        OAS_V31_SCHEMA: {
            'patches': [
                OAS_PATCH_DIR / 'v3.1' / 'preliminary-patch.json',
                OAS_PATCH_DIR / 'v3.1' / 'merge-patch.yaml',
            ],
            'outfile': PATCHED_OAS31_SCHEMA_PATH,
        },
        # META (the vocabulary metaschema) must be patched before DIALECT
        OAS_V31_SCHEMA_OBJ_EXTENSION_META: {
            'patches': [],
            'patches': [
                OAS_PATCH_DIR / 'v3.1' / 'extension-meta.yaml',
            ],
            'outfile': PATCHED_OAS31_META_PATH,
        },
        OAS_V31_SCHEMA_OBJ_DEFAULT_DIALECT: {
            'patches': [],
            'outfile': PATCHED_OAS31_DIALECT_PATH,
        },
    },
}


PATCH_SCHEMAS_DESCRIPTION = """
Load the standard OAS 3.x schemas from submodules/OpenAPI-Specification,
migrate older schemas to 2020-12 using alterschema, apply the appropriate
patches from patches/oas/..., and write the patched schemas to schemas/oas/...
with the same tree structure as in OpenAPI-Specification/schemas.  These
patched schemas should be checked in, matching the current state of the
submodule.  See CONTRIBUTING.md for more detail on when and how to update.

Note that currently only OAS v3.0 is supported.
"""

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
        with infile.open() as in_fp, outfiles[index].open(
            'w', encoding='utf-8'
        ) as out_fp:
            json.dump(yaml.safe_load(in_fp), out_fp, **kwargs)


def validate_schema(schema_data: Union[Mapping, bool], *metaschema_data: Sequence[Mapping], error_format='detailed'):
    """
    Validate a schema against its metaschema

    :param schema_data: The parsed schema data structure
    :param metaschema_data: Parsed metaschema data; this is only needed if
        :attr:`oascomply.catalog` has not been or cannot be configured
        to load the metaschema in ``"$schema"`` and any additional metaschemas
        that it references automatically; note that if metaschema A references
        metaschema B, then B *must* appear before A in the list
    :param error_format: The standard JSON Schema output format to use for error
        reporting; defaults to ``"detailed"``; other values are ``"basic"``
        or ``"verbose"``
    :returns: ``None`` if validaition is successful, or the error report
        in the format given by ``error_format`` if unsuccessful
    """
    # Constructing the Metaschema instances registers them
    # with the catalog, so we do not need to save the instances
    catalog = OASCatalog.get_catalog('oascomply')
    for md in metaschema_data:
        Metaschema(catalog, md)

    schema = JSONSchema(schema_data, catalog=catalog)
    result = schema.validate()

    if not result.valid:
        return result.output(error_format)
    return None


def apply_patches(target, patch_info):
    if 'alterschema' in patch_info:
        print(
            f'Running alterschema (draft4 to 2020-12) on "{OAS_V30_SCHEMA}", '
            'this may take a while...'
        )
        result = subprocess.run(
            [
                'alterschema',
                '--from',
                patch_info['alterschema']['from'],
                '--to',
                patch_info['alterschema']['to'],
                str(target),
            ],
            capture_output=True,
            encoding='utf-8',
            check=True,
        )

        # OrderedDict.move_to_end(..., last=False) moves to beginning.
        # Since "id" gets changed to "$id" it gets moved later in the dict.
        # "$defs" should be the last root-level keyword, so it getting
        # changed from "definitions" leaves it in the right place.
        schema = json.loads(result.stdout, object_hook=OrderedDict)
        schema.move_to_end('$id', last=False)
    else:
        with target.open(encoding='utf-8') as target_fd:
            schema = json.load(target_fd)

    for patch_file in patch_info['patches']:
        print(f'Opening patch "{patch_file}"')
        with patch_file.open(encoding='utf-8') as patch_fd:
            patch_data = (
                json.load(patch_fd) if patch_file.suffix == '.json'
                else yaml.safe_load(patch_fd)
            )
        if isinstance(patch_data, list):
            print(f'Applying JSON Patch (RFC 6902) "{patch_file}" ...')
            schema = JSONPatch(*patch_data).evaluate(schema)
        else:
            print(f'Applying JSON Merge Patch (RFC 7396) "{patch_file}" ...')
            json_merge_patch.merge(schema, patch_data)

    # move $defs to the end after patching in more root-level keywords.
    # Don't bother constructing an OrderedDict for this as supported
    # versions of python preserve insert order.
    if (defs := schema.get('$defs')) is not None:
        del schema['$defs']
        schema['$defs'] = defs

    print('Vaidating patched schema against its metaschema ...')
    with COMPLIANCE_VOCAB_METASCHEMA.open(encoding='utf-8') as vm_fp, \
         COMPLIANCE_DIALECT_METASCHEMA.open(encoding='utf-8') as dm_fp:
        vmeta = json.load(vm_fp)
        dmeta = json.load(dm_fp)

    if schema_errors := validate_schema(schema, vmeta, dmeta):
        sys.stderr.write('Metaschema validation failed!\n\n')
        json.dump(schema_errors, sys.stderr, indent=2, ensure_ascii=False)
        sys.stderr.write('\n')
        sys.exit(-1)

    patched_file = patch_info['outfile']
    print(f'Writing patched schema to "{patched_file}" ...')
    with open(patched_file, 'w', encoding='utf-8') as patched_fp:
        # For some reason there is no option for json.dump() to
        # include a trailing newline.
        json.dump(schema, patched_fp, indent=2, allow_nan=False)
        patched_fp.write('\n')


def patch():
    """Entry point for generating a patche OAS 3.0 schema (3.1 forthcoming)."""
    argparse.ArgumentParser(
        description=PATCH_SCHEMAS_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    ).parse_args()

    for oasversion in PATCHES:
        for target in PATCHES[oasversion]:
            print(f'Patching schema "{target}"...')
            apply_patches(target, PATCHES[oasversion][target])
            print(f'...done with schema "{target}"')
            print()
    print("Done with all schemas!")
    print()
