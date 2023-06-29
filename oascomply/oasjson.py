import re
import logging
from collections import defaultdict
from typing import Union

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
    'OasJson',
    'OasJsonError',
    'OasJsonTypeError',
    'OasJsonUnresolvableRefError',
    'OasJsonRefSuffixError',
]

logger = logging.getLogger(__name__)

OAS30_SUBSET_VOCAB = "https://spec.openapis.org/oas/v3.0/vocab/draft-04-subset"
OAS30_EXTENSION_VOCAB = "https://spec.openapis.org/oas/v3.0/vocab/extension"
OAS30_DIALECT_METASCHEMA = "https://spec.openapis.org/oas/v3.0/dialect/base"


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


# NOTE: This depends on the changes proposed in jschon PR #101,
#       currently available through the git repository as shown
#       in pyproject.toml.
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
        catalog='catalog',
        cacheid='default',
        **itemkwargs,
    ):
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

        self.uri = uri if isinstance(
            uri, rid.UriWithJsonPtr
        ) else rid.UriWithJsonPtr(str(uri))
        self.url = url if isinstance(
            url, rid.UriWithJsonPtr
        ) else rid.UriWithJsonPtr(str(url))

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

        self._to_resolve = []
        super().__init__(
            value,
            parent=parent,
            key=key,
            **itemkwargs,
        )

    def instantiate_mapping(self, value):
        schema_constructor = (
            # Note that we intentionally replace kwargs with self._schemakwargs
            lambda v, parent, key, uri, **kwargs: JSONSchema(
                v,
                parent=parent,
                key=key,
                uri=URI(str(uri)),
                metaschema_uri=self._oas_metaschema_uri,
                **self._schemakwargs,
            )
        )
        if str(self.path) == '/components/schemas':
            classes = defaultdict(lambda: schema_constructor)
        elif self.path and self.path[-1] == 'examples':
            classes = defaultdict(lambda: JSON)
        else:
            classes = defaultdict(lambda: type(self))
            classes['schema'] = schema_constructor
            classes['example'] = JSON
            classes['default'] = JSON
            classes['enum'] = JSON

        mapping = {}
        for k, v in value.items():
            mapping[k] = classes[k](
                v,
                parent=self,
                key=k,
                uri=self.uri.copy_with(fragment=self.uri.fragment / k),
                url=self.url.copy_with(fragment=self.url.fragment / k),
                **self.itemkwargs,
            )
            if isinstance(mapping[k], JSONSchema):
                root = self
                while root.parent is not None:
                    root = root.parent
                root._to_resolve.append(mapping[k])
        return mapping

    def resolve_references(self):
        for schema in self._to_resolve:
            if not isinstance(schema, JSONSchema):
                if isinstance(schema, OasJson):
                    # TODO: manage empty fragments better in general
                    # TODO: duplication with other raise OasJsonTypeError
                    uri = self.uri.copy_with(
                        fragment=None,
                    ) if self.uri.fragment == '' else self.uri
                    url = self.url.copy_with(
                        fragment=None,
                    ) if self.url.fragment == '' else self.url
                    raise OasJsonTypeError(uri=uri, url=url)
            try:
                schema._resolve_references()
            except CatalogError as e:
                import re
                if m := re.search(
                    'source is not available for "([^"]*)"',
                    str(e),
                ):
                    ref_uri = rid.Iri(m.groups()[0])
                    ref_resource_uri = ref_uri.to_absolute()
                    logger.warning(
                        f'Could not load referenced schema {ref_uri}, '
                        'checking for common configuration errors...',
                    )
                    for suffix in ('.json', '.yaml', '.yml'):
                        uri_with_suffix = f'{ref_resource_uri}{suffix}'
                        try:
                            if ref_schema := schema.catalog.get_schema(
                                URI(uri_with_suffix),
                                cacheid=schema.cacheid,
                            ):
                                raise OasJsonRefSuffixError(
                                    source_schema_uri=rid.Iri(
                                        str(schema.uri)
                                    ),
                                    ref_uri=ref_uri,
                                    ref_resource_uri=ref_resource_uri,
                                    target_resource_uri=rid.Iri(
                                        uri_with_suffix
                                    ),
                                    suffix=suffix,
                                ) from e
                        except CatalogError:
                            pass
                    raise OasJsonUnresolvableRefError(ref_uri)

                elif m := re.search(' ([^ ]*) is not a JSON Schema', str(e)):
                    uri = rid.Iri(m.groups()[0]).copy_with(
                        fragment=None,
                    ) if self.uri.fragment == '' else self.uri
                    url = None # self.url.copy_with(
                    #     fragment=None,
                    # ) if self.url.fragment == '' else self.url
                    raise OasJsonTypeError(uri=uri, url=url) from e
                raise

    def evaluate(self, instance: JSON, result: Result = None) -> Result:
        # TODO: manage empty fragments better in general
        uri = self.uri.copy_with(
            fragment=None,
        ) if self.uri.fragment == '' else self.uri
        url = self.url.copy_with(
            fragment=None,
        ) if self.url.fragment == '' else self.url
        raise OasJsonTypeError(uri=uri, url=url)
