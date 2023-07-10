import argparse
import re
import json
from pathlib import Path
import urllib
from uuid import uuid4
from collections import defaultdict, namedtuple
from typing import Any, Iterator, Mapping, Optional, Tuple, Type, Union
import logging
import os
import sys

import jschon

import rdflib
from rdflib.namespace import RDF

from oascomply import schema_catalog
from oascomply.oasgraph import (
    OasGraph, OasGraphResult, OUTPUT_FORMATS_LINE, OUTPUT_FORMATS_STRUCTURED,
)
from oascomply.schemaparse import (
    Annotation, SchemaParser, JsonSchemaParseError,
)
from oascomply.oasjson import (
    OasJson, OasJsonTypeError, OasJsonRefSuffixError,
    OasJsonUnresolvableRefError,
    _json_loadf, _yaml_loadf,
)
from oascomply.oas30dialect import OAS30_DIALECT_METASCHEMA
import oascomply.resourceid as rid

__all__ = [
    'ApiDescription',
]

logger = logging.getLogger(__name__)

HELP_PROLOG = """
Load and validate an API Description/Definition (APID).

The initial APID document is parsed immediately, with other documents parsed
as they are referenced.  The initial document is the first of:

1. The document from -i (--initial-document)
2. The first document from a -f (--file) containing an "openapi" field
3. The first document from a -u (--url) containing an "openapi" field 

All referenced documents MUST be provided in some form on the command line,
either individually (with -f or -u) or as a document tree to search (with
-d or -p).  Documents are loaded from their URL and referenced by their URI.

Each document's URL is the URL from which it was retrieved. If loaded from
a local filesystem path, the URL is the corresponding "file:" URL.

A document's URI is either determined from the URL (potentially as modified
by the -x, -D, and -P options), or set directly on the command line
(using additional arguments to -i, -f, -u, -d, or -p)..
This allows reference resolution to work even if the documents are not named
or deployed in the way the references expect.

See the "Loading APIDs and Schemas" tutorial for full documentation.
"""

HELP_EPILOG = """
See the README for further information on:

* How API description data appears in the output
* How to extract human-friendly names from the output
* API description document URLs vs URIs
* Handling multi-document API descriptions
* Handling complex referencing scenarios
* What you need to know about IRIs vs URIs/URLs
"""

ANNOT_ORDER = (
    'oasType',
    'oasReferences',
    'oasChildren',
    'oasLiterals',
    'oasExtensible',
    'oasApiLinks',
    'oasDescriptionLinks',
    'oasExamples',
)


UriPrefix = namedtuple('UriPrefix', ['directory', 'prefix'])
"""Utility class for option data mapping URI prefixes."""

class ApiDescription:
    """
    Representation of a complete API description.

    The constructor arguments are used to load the primary API description
    resource.  This resource MUST contain an ``openapi`` field setting
    the version.  Currently, 3.0.x descriptions are supported, with 3.1.x
    support intended for a later version.

    Note that at most one of ``path`` or ``url`` can be passed.

    :param document: The primary OAS document data
    :param uri: The URI for the primary OAS document
    :param path: The local filesystem path of the OAS document
    :param url: The URL from which the primary OAS document was retrieved
    :param sourcemap: A data structure mapping JSON pointer to lines and columns
    :param test_mode: If true, ensures that output can be used for repeatable
        testing by removing environment-specific information such as file names
    """

    def __init__(
        self,
        document: Any,
        uri: str,
        *,
        path: Optional[Path] = None,
        url: Optional[str] = None,
        sourcemap: Optional[Mapping] = None,
        test_mode: bool = False,
    ) -> None:
        assert url is None, "Remote URLs not yet supported"
        if uri is not None:
            # TODO: URI vs IRI terminology
            uri = rid.Iri(uri)
            assert uri.fragment is None, \
                "API description document URI cannot have a fragment"
        self._primary_uri = uri

        self._test_mode = test_mode

        if 'openapi' not in document:
            raise ValueError(
                "Initial API description must include `openapi` field!"
                f"{path} <{uri}>"
            )
        self._version = document['openapi']
        if not self._version.startswith('3.0.'):
            if self._version.startswith('3.1.'):
                raise NotImplementedError("OAS v3.1 support stil in progress")
            raise ValueError(f"OAS v{self._version} not supported!")

        if uri.path and '/' in uri.path and not uri.path.endswith('/'):
            # RDF serialization works better with a directory
            # as a base IRI, particularly for multi-document
            # API descriptions within a single directory.
            # Otherwise it fails to notice many opportunities to
            # shorten IRI-references.
            self._base_uri = uri.copy_with(
                path=uri.path[:uri.path.rindex('/') + 1]
            )
        else:
            self._base_uri = uri

        self._g = OasGraph(
            self._version[:self._version.rindex('.')],
            test_mode=test_mode,
        )

        self._contents = {}
        self._sources = {}
        self._validated = []

        self.add_resource(
            document=document,
            uri=self._primary_uri,
            path=path,
            sourcemap=sourcemap,
        )

    def add_resource(
        self,
        document: Any,
        uri: Union[str, rid.Iri],
        *,
        path: Optional[Path] = None,
        url: Optional[str] = None,
        sourcemap: Optional[Mapping] = None,
        oastype: Optional[str] = None,
    ) -> None:
        """
        Add a resource as part of the API description, and set its URI
        for use in resolving references and in the parser's output.

        Note that at most one of ``path`` or ``url`` can be passed.

        :param document: The parsed OAS document data
        :param uri: The URI of the OAS document
        :param path: The local filesystem path of the OAS document
        :param url: The URL from which the OAS document was retrieved
        :param sourcemap: Structure mapping JSON Pointers to lines and columns
        :param oastype: The semantic type of the document, typically
            used to indicate that a document is a stand-alone JSON Schema
            and must be parsed as such
        """
        assert url is None, "Remote URLs not yet supported"
        assert path is not None, "Must provide path for local document"

        url = rid.Iri(path.resolve().as_uri())
        if not isinstance(uri, rid.Iri):
            # TODO: URI vs IRI usage
            uri = rid.Iri(uri)
        assert uri.fragment is None, "Only complete documenets can be added."

        logger.info(f'Adding document "{path}" ...')
        logger.info(f'...URL <{url}>')
        logger.info(f'...URI <{uri}>')
        if oastype and oastype == 'Schema':
            logger.info(f'...instantiating JSON Schema <{uri}>')
            self._contents[uri] = jschon.JSONSchema(
                document,
                uri=jschon.URI(str(uri)),
                metaschema_uri=jschon.URI(OAS30_DIALECT_METASCHEMA),
                catalog='oascomply',
            )
            # assert isinstance(
        else:
            # The jschon.JSON class keeps track of JSON Pointer values for
            # every data entry, as well as providing parent links and type
            # information.  The OasJson subclass also automatically
            # instantiates jschon.JSONSchema classes for Schema Objects
            # and (in 3.0) for Reference Objects occupying the place of
            # Schema Objects.
            logger.info(f'...instantiating OAS Document <{uri}>')
            self._contents[uri] = OasJson(
                document,
                uri=uri,
                url=url,
                oasversion=self._version[:3],
            )
        if sourcemap:
            self._sources[uri] = sourcemap
        self._g.add_resource(url, uri, filename=path.name)

    def get_resource(self, uri: Union[str, rid.Iri], cacheid: str = 'default') -> Optional[Any]:
        logger.debug(f"Retrieving '{uri}' from cache '{cacheid}'")
        # TODO: URI library confusion
        return schema_catalog.get_resource(jschon.URI(str(uri)), cacheid=cacheid)

    def get_sourcemap(self, uri: Union[str, rid.Iri]):
        if not isinstance(uri, rid.IriWithJsonPtr):
            # TODO: IRI vs URI
            # TODO: Non-JSON Pointer fragments in 3.1
            uri = rid.IriWithJsonPtr(uri)

        return self._sources.get(uri.to_absolute())

    def validate(
        self,
        resource_uri=None,
        oastype='OpenAPI',
        validate_examples=True,
    ):
        sp = SchemaParser.get_parser({}, annotations=ANNOT_ORDER)
        errors = []
        if resource_uri is None:
            assert oastype == 'OpenAPI'
            resource_uri = self._primary_uri
        elif isinstance(resource_uri, str):
            # TODO: IRI vs URI
            # TODO: Non-JSON Pointer fragments in 3.1
            resource_uri = rid.IriWithJsonPtr(resource_uri)

        data = self.get_resource(resource_uri, cacheid='3.0')
        assert data is not None
        document = data.document_root
        sourcemap = self.get_sourcemap(resource_uri)

        try:
            output = sp.parse(data, oastype)
        except JsonSchemaParseError as e:
            logger.critical(
                f'JSON Schema validation of {resource_uri} failed!\n\n' +
                json.dumps(e.error_detail, indent=2),
            )
            sys.exit(-1)

        to_validate = {}
        by_method = defaultdict(list)
        for unit in output['annotations']:
            ann=Annotation(unit, instance_base=resource_uri.to_absolute())
            method = f'add_{ann.keyword.lower()}'

            # Using a try/except here can result in confusion if something
            # else produces an AttributeError, so use hasattr()
            if hasattr(self._g, method):
                by_method[method].append((ann, document, data, sourcemap))
            else:
                raise ValueError(f"Unexpected annotation {ann.keyword!r}")
        self._validated.append(resource_uri)

        for annot in ANNOT_ORDER:
            if annot == 'oasExamples':
                # By this point we have set up the necessary reference info
                for uri, oastype in to_validate.items():
                    if uri not in self._validated:
                        errors.extend(self.validate(
                            uri,
                            oastype,
                            validate_examples=validate_examples,
                        ))
                if not validate_examples:
                    logger.info('Skipping example validation')
                    continue

            method_name = f'add_{annot.lower()}'
            method_callable = getattr(self._g, method_name)
            for args in by_method[method_name]:
                graph_result = method_callable(*args)
                for err in graph_result.errors:
                    errors.append(err)
                for uri, oastype in graph_result.refTargets:
                    to_validate[uri] = oastype

        return errors

    def validate_graph(self):
        errors = []
        errors.extend(self._g.validate_json_references())
        return errors

    def serialize(
        self,
        *args,
        output_format='nt11',
        destination=sys.stdout,
        **kwargs
    ) -> Optional[Union[str, Iterator[str]]]:
        if self._test_mode:
            if output_format and output_format != 'nt11':
                sys.stderr.write('Only "nt11" supported in test mode!\n')
                sys.exit(-1)
            if destination not in (None, sys.stdout):
                sys.stderr.write(
                    'Only in-memory and stdout supported in test mode!\n',
                )
                sys.exit(-1)

            # TODO: At least sometimes, there is a blank line in the output.
            #       But there does not seem to be when serializeing directly
            #       to stdout.  This might be an issue with split(), in which
            #       case maybe use split()[:-1]?  Need to check performance
            #       with large graphs.
            filtered = filter(
                lambda l: l != '',
                sorted(self._g.serialize(output_format='nt11').split('\n')),
            )
            if destination is None:
                return filtered
            for line in filtered:
                print(line)
            return

        # Note that only lowercase "utf-8" avoids an encoding
        # warning with N-Triples output (and possibly other
        # serializers).  rdflib doesn't understand "UTF-8", but
        # confusingly uses "UTF-8" in the warning message.
        new_kwargs = {
            'encoding': 'utf-8',
            'base': self._base_uri,
            'output_format': output_format,
            'order': self._validated,
        }
        new_kwargs.update(kwargs)

        if destination in (sys.stdout, sys.stderr) and output_format != 'toml':
            # rdflib serializers write bytes, not str if destination
            # is not None, which doesn't work with sys.stdout / sys.stderr
            destination.flush()
            with os.fdopen(
                sys.stdout.fileno(),
                "wb",
                closefd=False,  # Don't close stdout/err exiting the with
            ) as dest:
                self._g.serialize(*args, destination=dest, **new_kwargs)
                dest.flush()
                return

        elif destination is None:
            return self._g.serialize(
                *args, destination=destination, **new_kwargs,
            )

        self._g.serialize(*args, destination=destination, **new_kwargs)

    @classmethod
    def _process_file_arg(
        cls,
        filearg,
        prefixes,
        create_source_map,
        strip_suffix,
    ):
        path = Path(filearg[0])
        full_path = path.resolve()
        oastype = None
        uri = None
        logger.debug(
            f'Processing {full_path!r}, strip_suffix={strip_suffix}...'
        )
        if len(filearg) > 1:
            try:
                uri = rid.IriWithJsonPtr(filearg[1])
                logger.debug(f'...assigning URI <{uri}> from 2nd arg')
            except ValueError:
                # TODO: Verify OAS type
                oastype = filearg[1]
                logger.debug(f'...assigning OAS type "{oastype}" from 2nd arg')
        if len(filearg) > 2:
            if uri is None:
                raise ValueError('2nd of 3 -f args must be URI')
            oastype = filearg[2]
            logger.debug(f'...assigning OAS type "{oastype}" from 3rd arg')

        for p in prefixes:
            try:
                rel = full_path.relative_to(p.directory)
                uri = rid.Iri(str(p.prefix) + str(rel.with_suffix('')))
                logger.debug(
                    f'...assigning URI <{uri}> using prefix <{p.prefix}>',
                )
            except ValueError:
                pass

        filetype = path.suffix[1:] or 'yaml'
        if filetype == 'yml':
            filetype = 'yaml'
        logger.debug(f'...determined filetype={filetype}')

        if uri is None:
            if strip_suffix:
                uri = rid.Iri(full_path.with_suffix('').as_uri())
            else:
                uri = rid.Iri(full_path.as_uri())
            logger.debug(
                f'...assigning URI <{uri}> from URL <{full_path.as_uri()}>',
            )

        if filetype == 'json':
            data, url, sourcemap = _json_loadf(full_path)
        elif filetype == 'yaml':
            data, url, sourcemap = _yaml_loadf(full_path)
        else:
            raise ValueError(f"Unsupported file type {filetype!r}")

        return {
            'data': data,
            'sourcemap': sourcemap,
            'path': path,
            'uri': uri,
            'oastype': oastype,
        }

    @classmethod
    def _process_prefix(cls, p):
        directory, prefix = p
        try:
            prefix = rid.Iri(prefix)
        except ValueError:
            try:
                rid.IriReference(prefix)
                raise ValueError(f'URI prefixes cannot be relative: <{p[0]}>')
            except ValueError:
                raise ValueError(
                    f'URI prefix <{p[0]}> does not appear to be a URI'
                )

        if prefix.scheme == 'file':
            raise ValueError(
                f"'file:' URIs cannot be used as URI prefixes: <{p[0]}>"
            )
        if prefix.query or prefix.fragment:
            raise ValueError(
                "URI prefixes cannot contain a query or fragment: "
                f"<{p[0]}>"
            )
        if not prefix.path.endswith('/'):
            raise ValueError(
                "URI prefixes must include a path that ends with '/': "
                f"<{p[0]}>"
            )

        path = Path(directory).resolve()
        if not path.is_dir():
            raise ValueError(
                "Path mapped to URI prefix must be an existing "
                f"directory: {p[1]!r}"
            )
        return UriPrefix(prefix=prefix, directory=path)

    @classmethod
    def _url_for(cls, uri):
        if uri.scheme != 'file':
            return None
        path = Path(uri.path)
        if path.exists():
            return uri
        for suffix in ('.json', '.yaml', '.ym'):
            ps = path.with_suffix(suffix)
            if ps.exists():
                return rid.Iri(ps.as_uri())
        return None

    @classmethod
    def load(cls):
        class CustomArgumentParser(argparse.ArgumentParser):
            def _fix_message(self, message):
                # nargs=+ does not support metavar=tuple
                return message.replace(
                    'INITIAL [INITIAL ...]',
                    'FILE|URL [URI]',
                ).replace(
                    'FILES [FILES ...]',
                    'FILE [URI] [TYPE]',
                ).replace(
                    'DIRECTORIES [DIRECTORIES ...]',
                    'DIRECTORY [URI_PREFIX]',
                ).replace(
                    'URLS [URLS ...]',
                    'URL [URI] [TYPE]',
                ).replace(
                    'PREFIXES [PREFIXES ...]',
                    'URL_PREFIX [URI_PREFIX]',
                )

            def format_usage(self):
                return self._fix_message(super().format_usage())

            def format_help(self):
                return self._fix_message(super().format_help())

        class AppendTuple(argparse.Action):
            def __init__(self, option_strings, dest, nargs=None, **kwargs):
                if nargs != '+':
                    raise ValueError(
                        f'{type(self).__name__}: expected nargs="+"'
                    )
                super().__init__(option_strings, dest, **kwargs)

            def __call__(self, parser, namespace, values, option_string=None):
                if len(values) not in (1, 2):
                    raise ValueError(
                        f'{type(self).__name__}: expected 1 or 2 arguments, '
                        f'got {len(values)}'
                    )
                if not hasattr(namespace, self.dest):
                    setattr(namespace, self.dest, [])
                getattr(namespace, self.dest).append(values)

        parser = CustomArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description=HELP_PROLOG,
            epilog=HELP_EPILOG,
            fromfile_prefix_chars='@',
        )
        parser.add_argument(
            '-i',
            '--initial-document',
            metavar='INITIAL',
            nargs='+',
            help="NOT YET IMPLEMENTED!!! "
                "The document from which to start validating; can "
                "follow the -f or -u syntax to load the document directly "
                "and assigne or calculate a URI, or give a path under the "
                "directory of a -d option or the URL prefix of a -p argument "
                "to assign a URI based on the -d or -p's URI prefix",
        )
        parser.add_argument(
            '-f',
            '--file',
            nargs='+',
            action='append',
            dest='files',
            help="An APID document as a local file, optionally followed by "
                 "a URI to use for reference resolution in place of the "
                 "corresponding 'file:' URL; this option can be repeated; "
                 "see also -x",
        )
        parser.add_argument(
            '-u',
            '--url',
            nargs='+',
            action='append',
            dest='urls',
            help="A URL for an APID document, optionally followed by a URI "
                 "to use for reference resolution; by default only 'http:' "
                 "and 'https:' URLs are supported; this option can be "
                 "repeated; see also -x",
        )
        parser.add_argument(
            '-x',
            '--strip-suffixes',
            nargs='*',
            default=('.json', '.yaml', '.yml'),
            help="For documents loaded with -f or -u without an explict URI "
                "assigned on the command line, assign a URI by stripping any "
                "of the given suffixes from the document's URL; passing this "
                "option without any suffixes disables this behavior, treating "
                "the unmodified URL as the URI; the default stripped suffixes "
                "are .json, .yaml, .yml",
        )
        parser.add_argument(
            '-d',
            '--directory',
            nargs='+',
            action='append',
            default=[],
            dest='directories',
            help="Resolve references matching the URI prefix from the given "
                "directory; if no URI prefix is provided, use the 'file:' URL "
                "corresponding to the directory as the prefix; this option "
                "can be repeated; see also -D",
        )
        parser.add_argument(
            '-p',
            '--url-prefix',
            nargs='+',
            action='append',
            default=[],
            dest='prefixes',
            help="Resolve references the URI prefix by replacing it with "
                "the given URL prefix, or directly from URLs matching the "
                "URL prefix if no URI prefix is provided; this option can be "
                "repeated; see also -P",
        )
        parser.add_argument(
            '-D',
            '--directory-suffixes',
            nargs='*',
            default=('.json', '.yaml', '.yml'),
            help="When resolving references using -d, try appending each "
                "suffix in order to the file path until one succeeds; "
                "the empty string can be passed to try loading the "
                "unmodified path first as JSON and then if that fails as "
                "YAML; the default suffixes are .json, .yaml .yml",
        )
        parser.add_argument(
            '-P',
            '--url-prefix-suffixes',
            nargs='*',
            default=(),
            help="When resolving references using -p, try appending each "
                "suffix in order to the URL until one succeeds; the empty "
                "string can be passed to try loading the unmodified URL "
                "which will be parsed based on the HTTP Content-Type header; "
                "by default, no suffixes are appended to URLs",
        )
        parser.add_argument(
            '-n',
            '--number-lines',
            action='store_true',
            help="Enable line and column numbers in the graph and in "
                 "error reproting; this has a considerable performance "
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
            '-t',
            '--store',
            default='none',
            choices=(('none',)),
            help="NOT YET IMPLEMENTED "
                 "TODO: Support storing to various kinds of databases.",
        )
        parser.add_argument(
            '-v',
            '--verbose',
            action='count',
            default=0,
            help="Increase verbosity; can passed twice for full debug output.",
        )
        parser.add_argument(
            '--test-mode',
            action='store_true',
            help="Omit data such as 'locatedAt' that will change for "
                 "every environment and produce sorted nt11 output.  "
                 "This is intended to facilitate "
                 "automated testing of the entire system.",
        )
        args = parser.parse_args()
        if args.verbose:
            if args.verbose == 1:
                logging.basicConfig(level=logging.INFO)
            else:
                logging.basicConfig(level=logging.DEBUG)
        else:
            logging.basicConfig(level=logging.WARN)

        # TODO: Fix temporary hack
        strip_suffix = not bool(args.strip_suffixes)
        logger.debug(f'Processed arguments:\n{args}')

        if args.initial_document:
            raise NotImplementedError('-i option not yet implemented')

        try:
            # TODO: prefixes -> directories migration/split
            prefixes = [cls._process_prefix(p) for p in args.directories]
        except ValueError as e:
            logger.error(str(e))
            sys.exit(-1)

        # Reverse sort so that the first matching prefix is the longest
        # TODO: At some point I switched the tuple order, does this still work?
        prefixes.sort(reverse=True)

        resources = [cls._process_file_arg(
            filearg,
            prefixes,
            args.number_lines is True,
            strip_suffix,
        ) for filearg in args.files]

        candidates = list(filter(lambda r: 'openapi' in r['data'], resources))
        if not candidates:
            logger.error("No document contains an 'openapi' field!")
            return -1
        primary = candidates[0]

        desc = ApiDescription(
            primary['data'],
            primary['uri'],
            path=primary['path'],
            sourcemap=primary['sourcemap'],
            test_mode=args.test_mode,
        )
        for r in resources:
            if r['uri'] != primary['uri']:
                desc.add_resource(
                    r['data'],
                    r['uri'],
                    path=r['path'],
                    sourcemap=r['sourcemap'],
                    oastype=r['oastype'],
                )

        errors = desc.validate(validate_examples=(args.examples == 'true'))
        errors.extend(desc.validate_graph())
        if errors:
            for err in errors:
                logger.error(json.dumps(err['error'], indent=2))

            sys.stderr.write('\nAPI description contains errors\n\n')
            sys.exit(-1)

        if args.output_format is not None or args.test_mode is True:
            desc.serialize(output_format=args.output_format)

        sys.stderr.write('Your API description is valid!\n')
