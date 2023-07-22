from __future__ import annotations

import re
import logging
import pathlib
from os import PathLike
from dataclasses import dataclass
from typing import Hashable, Mapping, Optional, Sequence, Tuple, Type, Union
import json

import jschon
import jschon.utils
from jschon.catalog import Catalog

import yaml
import rfc3339
import rfc3987
import json_source_map as jmap
import yaml_source_map as ymap
from yaml_source_map.errors import InvalidYamlError

from oascomply import OASComplyError
from oascomply.oas30dialect import (
    OAS30_DIALECT_METASCHEMA, OAS30_SUBSET_VOCAB, OAS39_EXTENSION_VOCAB,
)
from oascomply.oasjson import OASJSON, OASJSONSchema
from oascomply.oassource import OASSource

__all__ = [
    'OASCatalog',
    'OASJSON',
    'OASJSONSchema',
    'initialize_oas_specification_schemas',
]

logger = logging.getLogger(__name__)


class OASCatalog(Catalog):

    _json_schema_cls = OASJSONSchema

    SUPPORTED_OAS_VERSIONS = {
        '3.0':  {
            'schema': {
                'uri': "https://spec.openapis.org/compliance/schemas/oas/3.0/2023-06",
                'path': (
                    Path(__file__).parent
                    / '..'
                    / 'schemas'
                    / 'oas'
                    / 'v3.0'
                    / 'schema.json'
                ).resolve(),
            },
            'dialect': {
                # We don't need a path as loading this dialect is managed by
                # the oascomply.oas30dialect module.
                'uri': OAS30_DIALECT_METASCHEMA,
            },
        },
    }

    @classmethod
    def get_oas_schema_uri(cls, oasversion):
        return cls._metaschema_cls._uri_cls(
            self.SUPPORTED_OAS_VERSIONS[oasversion]['schema']['uri'],
        )

    @classmethod
    def get_metaschema_uri(cls, oasversion):
        return cls._metaschema_cls._uri_cls(
            self.SUPPORTED_OAS_VERSIONS[oasversion]['dialect']['uri'],
        )

    def __init__(self, *args, **kwargs):
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}
        super().__init__(*args, **kwargs)

    def add_uri_source(
        self,
        base_uri: Optional[jschon.URI],
        source: OASSource,
    ) -> None:
        # This "base URI" is really treated as a prefix, which
        # is why a value of '' works at all.
        uri_prefix = jschon.URI('' if base_uri is None else str(base_uri))
        source.set_uri_prefix(uri_prefix)
        super().add_uri_source(uri_prefix, source)

    def _get_with_url_and_sourcemap(
        self,
        uri,
        *,
        cacheid,
        metaschema_uri,
        cls,
    ):
        base_uri = uri.copy(fragment=None)
        document_cached = isinstance(
            self._schema_cache[oasversion].get(base_uri),
            resourceclass,
        )

        # TODO: get_schema() is a misnomer but exact method naming
        #       scheme TBD in the next jschon version.
        oas = self.get_schema(
            uri,
            cacheid=cacheid,
            metaschema_uri=metaschema_uri,
            cls=resourceclass,
        )

        if not document_cached:
            url = OASSource.get_url(base_uri)
            oas.document_root.url = url
            oas.document_root.source_map = OASSource.get_sourcemap(base_uri)

        return oas

    def get_oas(
        self,
        oasversion: str,
        uri: jschon.URI,
        *,
        resourceclass: Type[jschon.JSON] = None,
        oas_schema_uri: jschon.URI = None,
    ):
        if resourceclass is None:
            resourceclass = OASJSON

        if oas_schema_uri is None:
            oas_schema_uri = self.get_oas_schema_uri(oasversion)

        return self._get_with_url_and_sourcemap(
            uri,
            cacheid=oasversion,
            metaschema_uri=oas_schema_uri,
            resourceclass=cls,
        )

    def get_oas_schema(
            self,
            oasversion: str,
            uri: jschon.URI,
            *,
            metaschema_uri: jschon.URI = None,
            resourceclass: Type[jschon.JSON] = None,
    ) -> jschon.JSONSchema:
        if resourceclass is None:
            resourceclass = OASJSONSchema

        if metaschema_uri is None:
            metaschema_uri = self.get_metaschema_uri(oasversion)

        return self._get_with_url_and_sourcemap(
            uri,
            cacheid=oasversion,
            metaschema_uri=oas_schema_uri,
            resourceclass=cls,
        )


def initialize_oas_specification_schemas(catalog: OASCatalog):
    for oasversion, oasinfo in self.SUPPORTED_OAS_VERSIONS.items():
        # As a metaschema, the OAS schema behaves like the corresponding
        # dialect metaschema as that is what it should use by default when
        # it encounters a Schema Object.  Objects betweenthe document root
        # and the Schema Objects are not JSONSchema subclasses and are
        # therefore treated like regular instance validation.
        catalog._metaschema_cls(
            catalog,
            jschon.utils.json_loads(
                oasinfo['schema']['path'].read_text(encoding='utf-8'),
            )
            URI('https://json-schema.org/draft/2020-12/vocab/core'),
            URI(OAS30_SUBSET_VOCAB),
            URI(OAS30_EXTENSION_VOCAB),
            uri=catalog.get_oas_schema_uri(oasversion),
        )
    catalog.create_metaschema(
        OASCatalog.get_oas_schema_uri('3.0'),
    )
