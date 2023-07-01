import re
import logging
from collections import defaultdict
from typing import Hashable, Union

from jschon import JSON, JSONCompatible, JSONSchema, Result, URI
from jschon.catalog import Catalog, CatalogError
from jschon.jsonpointer import RelativeJSONPointer
from jschon.vocabulary.format import format_validator
from jschon.vocabulary import (
    Keyword, KeywordClass, Metaschema, ObjectOfSubschemas, Subschema,
    Vocabulary, format as format_, annotation, applicator, validation,
)

import rfc3339
import rfc3987

from oascomply.ptrtemplates import (
    JSON_POINTER_TEMPLATE, RELATIVE_JSON_POINTER_TEMPLATE,
    RelJsonPtrTemplate,
)
import oascomply.resourceid as rid

__all__ = [
    'OasCatalog',
    'OasJson',
    'OasJsonError',
    'OasJsonTypeError',
    'OasJsonUnresolvableRefError',
    'OasJsonRefSuffixError',
]

logger = logging.getLogger(__name__)


class OasCatalog(Catalog):
    def get_resource(self, uri, *, cacheid='default'):
        return self._schema_cache[cacheid][uri]

    def get_schema(
            self,
            uri: URI,
            *,
            metaschema_uri: URI = None,
            cacheid: Hashable = 'default',
    ) -> JSONSchema:
        try:
            return super().get_schema(
                uri,
                metaschema_uri=metaschema_uri,
                cacheid=cacheid,
            )
        except CatalogError as e:
            if 'not a JSON Schema' not in str(e):
                raise

            base_uri = uri.copy(fragment=False)
            resource = self.get_resource(base_uri, cacheid=cacheid)
            self.del_schema(uri)

            if uri.fragment is None or uri.fragment == '':
                self.del_schema(base_uri)
                # TODO: .value vs .data
                return JSONSchema(
                    resource.value,
                    uri=uri,
                    metaschema_uri=metaschema_uri,
                    catalog=self,
                    cacheid=cacheid,
                )
            if not uri.fragment.startswith('/'):
                raise ValueError(
                    'Non-JSON Pointer fragments not yet supported',
                )
            ptr = rid.JsonPtr.parse_uri_fragment(uri.fragment)
            parent_ptr = ptr[:-1]
            key = ptr[-1]

            parent = parent_ptr.evaluate(resource)
            return parent.convert_to_schema(key)


class OasJsonError(Exception):
    """Base class for errors raised by :class:`OasJson`"""
    def __str__(self):
        return self.args[0]


class OasJsonTypeError(OasJsonError, TypeError):
    """Indicates an attempt to treat an OasJson as a jschon.JSONSchema"""
    def __init__(self, uri, url):
        super().__init__('Cannot evaluate OasJson as JSONSchema', uri, url)

    @property
    def uri(self):
        """The URI of the mis-typed resource (possiby same as the URL)"""
        return self.args[1]

    @property
    def url(self):
        """The URL of the mis-typed resource"""
        return self.args[2]


class OasJsonUnresolvableRefError(OasJsonError, ValueError):
    """Indicates that a reference target could not be found."""
    def __init__(self, ref_uri):
        super().__init__(
            f"Could not resolve reference to {ref_uri}",
            ref_uri,
        )

    @property
    def ref_uri(self):
        return self.args[1]


class OasJsonRefSuffixError(OasJsonError, ValueError):
    """Indicates misuse of filesystem suffixes in retrieving a resource."""
    def __init__(
        self,
        source_schema_uri,
        ref_uri,
        ref_resource_uri,
        target_resource_uri,
        suffix,
    ):
        super().__init__(
            f"Reference without suffix attempted despite target resource "
            f"being registered under a URI with suffix",
            source_schema_uri,
            ref_uri,
            ref_resource_uri,
            target_resource_uri,
            suffix,
        )

    @property
    def source_schema_uri(self):
        return self.args[1]

    @property
    def ref_uri(self):
        return self.args[2]

    @property
    def ref_resource_uri(self):
        return self.args[3]

    @property
    def target_resource_uri(self):
        return self.args[4]

    @property
    def suffix(self):
        return self.args[5]


class OasJson(JSON):
    """
    Representation of an OAS-complaint API document.

    Based on and derived from :class:`jschon.json.JSON`

    :param uri: The identifier of this document, used for resolving references
    :param url: The locator of this document, from which it was loaded
    :param parent: The parent :class:`jschon.json.JSON` instance, if any
    :param key: The keyword under which this object appears in the parent
    :param itemclass: The class to use to instantiate child objects
    """
    def __init__(
        self,
        value,
        *,
        uri=None,
        url=None,
        parent=None,
        key=None,
        itemclass=None,
        catalog='oascomply',
        cacheid='default',
        **itemkwargs,
    ):
        logger.info(f'OasJson(uri={str(uri)!r}, url={str(url)!r}, ...)')

        if itemclass is None:
            itemclass = OasJson

        if 'oasversion' not in itemkwargs:
            if 'openapi' not in value:
                raise ValueError(
                    f"{type(self)} requires the 'openapi' field "
                    "or an 'oasversion' constructor parameter",
                )

            # Chop off patch version number
            itemkwargs['oasversion'] = value['openapi'][:3]

        if 'oas_metaschema_uri' not in itemkwargs:
            if itemkwargs['oasversion'] == '3.1':
                itemkwargs['oas_metaschema_uri'] = URI(value.get(
                    'jsonSchemaDialect',
                    "https://spec.openapis.org/oas/3.1/dialect/base",
                ))
            elif itemkwargs['oasversion'] == '3.0':
                itemkwargs['oas_metaschema_uri'] = URI(
                    "https://spec.openapis.org/oas/v3.0/dialect/base",
                )
            else:
                raise ValueError(
                    f"Unsupported OAS version {value['openapi']}",
                )
        self._oas_metaschema_uri = itemkwargs['oas_metaschema_uri']
        self._oasversion = itemkwargs['oasversion']
        if uri is None:
            # TODO: JsonPtr vs str
            self.uri = parent.uri.copy_with(
                fragment=rid.JsonPtr.parse_uri_fragment(
                    str(parent.uri.fragment),
                ) / key,
            )
        elif isinstance(uri, rid.UriWithJsonPtr):
            self.uri = uri
        else:
            self.uri = rid.UriWithJsonPtr(str(uri))

        if url is None:
            # TODO: JsonPtr vs str
            self.url = parent.url.copy_with(
                fragment=rid.JsonPtr.parse_uri_fragment(
                    str(parent.url.fragment),
                ) / key,
            )
        elif isinstance(url, rid.UriWithJsonPtr):
            self.url = url
        else:
            self.url = rid.UriWithJsonPtr(str(url))

        if not isinstance(catalog, Catalog):
            catalog = Catalog.get_catalog(catalog)

        # Track position with JSON Pointer fragments, so ensure we have one
        # TODO: Sometimes we don't want an empty fragment on the root document.
        if not self.uri.fragment:
            if self.uri.fragment is None:
                catalog.add_schema(URI(str(self.uri)), self, cacheid=cacheid)
                self.uri = self.uri.copy_with(fragment='')
            else:
                catalog.add_schema(
                    URI(str(self.uri.to_absolute())),
                    self,
                    cacheid=cacheid,
                )
        if not self.url.fragment:
            self.url = self.url.copy_with(fragment='')

        self._schemakwargs = itemkwargs.copy()
        del self._schemakwargs['oasversion']
        del self._schemakwargs['oas_metaschema_uri']
        self._schemakwargs['catalog'] = catalog
        self._schemakwargs['cacheid'] = cacheid
        self._value = value

        super().__init__(
            value,
            parent=parent,
            key=key,
            itemclass=itemclass,
            **itemkwargs,
        )

    def convert_to_schema(self, key):
        if not isinstance(self.data[key], JSONSchema):
            # TODO: Figure out jschon.URI vs rid.Uri*
            # TODO: .value vs .data
            self.data[key] = JSONSchema(
                self.data[key].value,
                parent=self,
                key=key,
                uri=URI(str(
                    self.uri.copy_with(fragment=self.uri.fragment / key),
                )),
                metaschema_uri=URI(str(self._oas_metaschema_uri)),
                **self._schemakwargs,
            )
            self.data[key]._resolve_references()
        return self.data[key]
