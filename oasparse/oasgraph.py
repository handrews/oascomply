import json
from pathlib import Path
from uuid import uuid4
from typing import Any, Optional
import logging

import jschon
import rfc3987
import rdflib
from rdflib.namespace import RDF
import yaml

__all__ = [
    'OasGraph',
]

logger = logging.getLogger(__name__)


class OasGraph:
    def __init__(self, version, base=None):
        if version not in ('3.0', '3.1'):
            raise ValueError(f'OAS v{version} is not supported.')
        if version == '3.1':
            raise ValueError(f'OAS v3.1 support TBD.')

        self._g = rdflib.Graph(base=rdflib.URIRef(base))
        self._oas = rdflib.Namespace(
            f'https://spec.openapis.org/oas/v{version}/ontology#'
        )
        self._g.bind('oas3.0', self._oas)

    def serialize(self, *args, **kwargs):
        return self._g.serialize(*args, **kwargs)

    def add_resource(self, location, iri):
        rdf_node = rdflib.URIRef(iri)
        self._g.add((
            rdf_node,
            self._oas['locatedAt'],
            rdflib.URIRef(
                location.resolve().as_uri() if isinstance(location, Path)
                else location,
            ),
        ))
        filename = None
        if isinstance(location, Path):
            filename = location.name
        else:
            path = rfc3987.parse(location, rule='IRI')['path']
            if '/' in path:
                filename = path.split('/')[-1]

        if filename:
            self._g.add((
                rdf_node,
                self._oas['filename'],
                rdflib.Literal(filename),
            ))

    def add_oastype(self, annotation, instance):
        # to_rdf()
        instance_uri = rdflib.URIRef(str(annotation.location.instance_uri))
        self._g.add((
            instance_uri,
            RDF.type,
            self._oas[annotation.value],
        ))
        self._g.add((
            instance_uri,
            RDF.type,
            self._oas['ParsedStructure'],
        ))

    def add_oaschildren(self, annotation, instance):
        location = annotation.location
        # to_rdf()
        parent_uri = rdflib.URIRef(str(location.instance_uri))
        for child in annotation.value:
            child = child.value
            if '{' in child:
                continue

            child_ptr = jschon.RelativeJSONPointer(child)
            parent_obj = location.instance_ptr.evaluate(instance)
            try:
                child_obj = child_ptr.evaluate(parent_obj)
                child_path = child_obj.path
                iu = location.instance_uri
                # replace fragment; to_rdf
                child_uri = rdflib.URIRef(str(iu.copy(
                    fragment=child_path.uri_fragment(),
                )))
                self._g.add((
                    parent_uri,
                    self._oas[child_ptr.path[0]],
                    child_uri,
                ))
                self._g.add((
                    child_uri,
                    self._oas['parent'],
                    parent_uri,
                ))
            except jschon.RelativeJSONPointerError as e:
                logger.error(str(e))

    def add_oasreferences(self, annotation, instance):
        location = annotation.location
        remote_resources = []
        for refloc, reftype in annotation.value.items():
            reftype = reftype.value
            # if '{' in refloc:
                # continue
            try:
                ref_ptr = jschon.RelativeJSONPointer(refloc)
                parent_obj = location.instance_ptr.evaluate(instance)
                ref_obj = ref_ptr.evaluate(parent_obj)
                ref_source_path = ref_obj.path
                iu = location.instance_uri
                # replace fragment; to_rdf
                ref_src_uri = rdflib.URIRef(str(
                    iu.copy(fragment=ref_source_path.uri_fragment())
                ))
                ref_target_uri = rdflib.URIRef(str(
                    jschon.URI(ref_obj.value).resolve(iu)
                ))
                self._g.add((
                    ref_src_uri,
                    self._oas['references'],
                    ref_target_uri,
                ))
                # TODO: elide the reference with a new edge

                # compare absolute forms
                logger.error(f'{ref_src_uri.defrag()} != {ref_target_uri.defrag()}')
                if ref_src_uri.defrag() != ref_target_uri.defrag():
                    logger.error(f'Pushing {ref_target_uri}')
                    if reftype is True:
                        # TODO: Handle this correctly, for now just
                        #       assume Schema as a test run.
                        reftype = 'Schema'
                    remote_resources.append((str(ref_target_uri), reftype))
            except (ValueError, jschon.RelativeJSONPointerError) as e:
                logger.error(str(e))
        return remote_resources
