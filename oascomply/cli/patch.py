import sys
import argparse

from oascomply.patch import PATCHES, apply_patches


PATCH_SCHEMAS_DESCRIPTION = """
Load the standard OAS 3.x schemas from submodules/OpenAPI-Specification,
migrate older schemas to 2020-12 using alterschema, apply the appropriate
patches from patches/oas/..., and write the patched schemas to schemas/oas/...
with the same tree structure as in OpenAPI-Specification/schemas.  These
patched schemas should be checked in, matching the current state of the
submodule.  See CONTRIBUTING.md for more detail on when and how to update.

Note that currently only OAS v3.0 is supported.
"""


def patch():
    """Entry point for generating a patche OAS 3.0 schema (3.1 forthcoming)."""
    parser = argparse.ArgumentParser(
        description=PATCH_SCHEMAS_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'versions',
        nargs='*',
        help='OAS versions to patch in X.Y form; all versions are patched '
            'if no versions are passed.'
    )
    args = parser.parse_args()

    success = True
    for oasversion in PATCHES:
        if args.versions and oasversion not in args.versions:
            continue
        for target in PATCHES[oasversion]:
            print(f'Patching schema "{target}"...')
            success &= apply_patches(target, PATCHES[oasversion][target])
            print(f'...done with schema "{target}"')
            print()
    if success:
        print("Done with all schemas!")
        print()
    else:
        print(
            "ERROR: Some patches produced invalid schema(s)!\n"
                "  Check for '.INVALID.json' files for failed schemas.",
            file=sys.stderr,
        )
        print('', file=sys.stderr)
