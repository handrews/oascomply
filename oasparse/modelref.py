import sys, os.path, io, logging, json
from collections import defaultdict

from ruamel.yaml import YAML
yaml=YAML(typ='safe')
yaml.default_flow_style = False
yaml.indent(offset=2)

import rfc3986

import jschon, jschon.catalog
from jschon.jsonpointer import JSONPointer

import rdflib
from rdflib.namespace import RDF

from modelRef4jschon import AtModelReference

log = logging.getLogger('modelref')
log.setLevel(logging.DEBUG)

LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(LOCAL_DIR, '..', 'schemas')
INSTANCE_DIR = os.path.join(LOCAL_DIR, '..', 'instances')

DOCUMENT_BASE_URI = 'https://example.com/'

class InMemorySource(jschon.catalog.Source):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._registry = {}

    def register(self, relative_path, schema):
        self._registry[relative_path] = schema

    def __call__(self, relative_path):
        return self._registry[relative_path]

def init_jschon():
    catalog = jschon.create_catalog('2020-12')

    in_memory_source = InMemorySource()
    with \
        open(os.path.join(SCHEMA_DIR, 'meta', 'modelref.json')) as mfd, \
        open(os.path.join(SCHEMA_DIR, 'dialect', 'modelref.json')) as dfd \
    :
        in_memory_source.register('meta/2020-12/modelref', json.load(mfd))
        in_memory_source.register('dialect/2020-12/modelref', json.load(dfd))

    catalog.add_uri_source(
        jschon.URI('https://example.com/reference/'),
        in_memory_source,
    )
    catalog.create_vocabulary(
        jschon.URI('https://example.com/reference/vocab/2020-12/modelref'),
        AtModelReference,
    )
    catalog.create_metaschema(
        jschon.URI(
            'https://example.com/reference/dialect/2020-12/modelref'
        ),
        jschon.URI("https://json-schema.org/draft/2020-12/vocab/core"),
    )
    return catalog

class Parser:
    def __init__(
        self,
        instance_name,
        instance_base_uri=DOCUMENT_BASE_URI,
        use_rdf=True,
        rdf_format='json-ld',
        type_filter=(),
        clear_storage=True,
    ):
        self._instance_name = instance_name
        self._instance = None

        if instance_base_uri == DOCUMENT_BASE_URI:
            # We're using the default base URI, so at least customize
            # it with the name we have for this API description.
            self._instance_base_uri = rfc3986.uri_reference(instance_name) \
                .resolve_with(instance_base_uri)
        else:
            self._instance_base_uri = instance_base_uri

        # We don't use the catalog directly, but its presence
        # lets us know that jschon has been set up properly.
        self._jschon_catalog = None

        # Initialize the stack with the root pointer, which is never popped.
        self._stack = [JSONPointer('')]
        self._seen = {}
        self._refs = {}

        self._oastypes = {}
        self._type_filter = type_filter
        self._filtered = []

        # If we are using a persistant data store, should we clear it?
        self._clear_storage = clear_storage

        self._use_rdf = use_rdf
        self._rdf_g = None
        self._rdf_nodes = {}

    def __enter__(self):
        if self._use_rdf:
            self._rdf_g = rdflib.Graph()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    def parse(self):
        # TODO: Are we likely to re-invoke parse()?  Why?
        #       Is there a reason to not just parse on instantiation?
        #       Would we re-parse into different graphs?
        #       Serialize the parsed graph different ways?
        if not self._instance:
            self._instance = self._load_instance()

        if not self._jschon_catalog:
            self._jschon_catalog = init_jschon()

        self._schema_output = self._evaluate_instance()
        return

        for r in sorted(
            self._schema_output['annotations'],
            key=lambda a: a['instanceLocation']
        ):
            akl = r['absoluteKeywordLocation']
            if akl.endswith('/oasType'):
                self._handle_oastype(r)

        self._link_references()

    def _load_instance(self):
        instance_file = os.path.join(INSTANCE_DIR, f'{self._instance_name}.json')
        try:
            with open(instance_file) as instance_fd:
                return json.load(instance_fd)

        except FileNotFoundError:
            log.debug(f'File "{instance_file}" does not exist')
            log.error(f'API description "{self._instance_name}" not found')
            sys.exit(-1)

    def _evaluate_instance(self):
        try:
            schema_file = os.path.join(SCHEMA_DIR, 'ypr.json')
            with open(schema_file) as schema_fd:
                schema_data = json.load(schema_fd)

            init_jschon()
            schema = jschon.JSONSchema(schema_data)
            result = schema.evaluate(jschon.JSON(self._instance))

            if not result.valid:
                log.error(f'Instance not valid')
                if log.isEnabledFor(logging.DEBUG):
                    # TODO: I don't understand/remember the logging config,
                    #       as log.debug won't work here for some reason.
                    schema_errors = io.StringIO()
                    yaml.dump(result.output('detailed'), schema_errors)
                    log.error('\n' + schema_errors.getvalue())
                sys.exit(-1)
            return result.output('basic')

        except FileNotFoundError:
            log.debug(f'File "{schema_file}" does not exist')
            log.error(f'Schema for OAS v{version} not not found')
            sys.exit(-1)

    def serialize_annotations(self, exclude_internal=True):
        output = {
            'valid': self._schema_output['valid'],
            'details': [],
        }

        units = {}
        # defaultdict(lambda: {
        #     'valid': True,
        #     'schemaLocation': None,
        #     'instanceLocation': None,
        #     'evaluationPath': None,
        #     'keyword': None,
        #     'annotations': {},
        # }
        entry_schema_uri = None
        for a in self._schema_output['annotations']:
            ep_ptr = JSONPointer(a['keywordLocation'])
            keyword = JSONPointer.unescape(ep_ptr[-1])

            akl = a['absoluteKeywordLocation']
            sl = akl[:akl.rindex('/')]
            il = a['instanceLocation']
            ep = str(JSONPointer(ep_ptr[:-1]))

            if ep == '':
                entry_schema_uri = rfc3986.uri_reference(sl)

            unit_key = (sl, il, ep)
            unit = units.get(
                unit_key,
                {
                    'valid': True,
                    'schemaLocation': sl,
                    'instanceLocation': il,
                    'evaluationPath': ep,
                    'annotations': {},
                }
            )
            unit['annotations'][keyword] = a['annotation']
            units[unit_key] = unit

        output['details'] = [u for u in units.values()]

        web_annotations = self.build_web_annotations(
            output,
            entry_schema_uri,
            exclude_internal=exclude_internal,
        )

        json.dump(output, sys.stdout, indent=2)
        print('')
        print('')
        json.dump(web_annotations, sys.stdout, indent=2)
        print('')

    # These keywords use annotations for internal communcation,
    # which is usually not of interest to end users.
    INTERNAL_ANNOTATIONS = (
        'properties', 'patternProperties', 'additionalProperties',
        'unevaluatedProperties', 'unevaluatedItems', 'if',
        'prefixItems', 'items', 'contains', 'minContains', 'maxContains',
    )
    DEFAULT_INSTANCE_BASE_URI = rfc3986.uri_reference(
        'https://example.com/instances/',
    )
    def build_web_annotations(
        self,
        output,
        entry_schema_uri,
        # instance_base_uri=DEFAULT_INSTANCE_BASE_URI,
        exclude_internal=True,
    ):
        json.dump(output, sys.stdout, indent=2)
        web_annotations = []
        for unit in output['details']:
            for keyword, value in unit['annotations'].items():
                if not (
                    exclude_internal and keyword in self.INTERNAL_ANNOTATIONS
                ):
                    print(unit)
                    web_annotations.append(
                        self._unit_to_web_annotation(
                            unit,
                            keyword,
                            output,
                            entry_schema_uri,
                            # instance_base_uri,
                        )
                    )

        web_ann_coll = {
            '@context': 'http://www.w3.org/ns/anno.jsonld',
            'id': 'https://example.com/collections/1',
            'type': 'AnnotationCollection',
            'label': 'Annotations from JSON Schema evaluation',
            'total': len(web_annotations),
            'first': {
                'id': 'https://example.com/collections/1/pages/1',
                'type': 'AnnotationPage',
                'startIndex': 0,
                'items': web_annotations,
            },
        }
        return web_ann_coll

    def _unit_to_web_annotation(
        self,
        unit,
        keyword,
        output,
        entry_schema_uri,
        # instance_base_uri=DEFAULT_INSTANCE_BASE_URI,
    ):
        ep = unit['evaluationPath']
        ep_uri = entry_schema_uri.copy_with(
            fragment=(JSONPointer(ep) / keyword).uri_fragment(),
        )
        sl_uri = rfc3986.uri_reference(unit['schemaLocation'])
        body_ptr = JSONPointer.parse_uri_fragment(sl_uri.fragment) / keyword
        body_uri = sl_uri.copy_with(fragment=body_ptr.uri_fragment())
        
        return {
            '@context': 'http://www.w3.org/ns/anno.jsonld',
            'id': ep_uri.unsplit(),
            'type': 'Annotation',
            'bodyValue': unit['annotations'][keyword], # body_uri.unsplit(),
            'target': self._instance_base_uri.copy_with(
                fragment=JSONPointer(
                    unit['instanceLocation']
                ).uri_fragment()
            ).unsplit(),
        }

    def serialize_rdf(self, fmt='turtle'):
        print(self._rdf_g.serialize(format=fmt))

if __name__ == '__main__':
    argc = len(sys.argv) - 1
    instance_name = sys.argv[1] if argc > 0 else 'ypr'
    graph_type = sys.argv[2] if argc > 1 else 'rdf'
    serialize_only = argc > 2
    with Parser(
        instance_name,
        use_rdf=graph_type == 'rdf',
        clear_storage=(not serialize_only)
    ) as parser:
        if not serialize_only:
            parser.parse()

        if graph_type == 'rdf':
            parser.serialize_rdf()

        elif graph_type =='annotations':
            parser.serialize_annotations()
