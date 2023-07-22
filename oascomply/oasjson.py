from __future__ import annotations

import re
import logging
import pathlib
from os import PathLike
from dataclasses import dataclass
from typing import Hashable, Mapping, Optional, Sequence, Tuple, Type, TYPE_CHECKING, Union
import json

import jschon
import jschon.utils
from jschon.jsonschema import JSONSchemaContainer

from oascomply import resourceid as rid
from oascomply.oas30dialect import OAS30_DIALECT_METASCHEMA

if TYPE_CHECKING:
    from oascomply.oascatalog import OASCatalog

__all__ = [
    'OASJSON',
    'OASJSONSchema',
]

logger = logging.getLogger(__name__)


class OASJSONMixin:
    """Interface for JSON classes implementing OAS documents"""

    @property
    def oasversion(self) -> str:
        """The major and minor (X.Y) part of the "openapi" version string"""
        if self._oasversion is None:
            if self is self.document_root:
                if 'openapi' not in self.data:
                    raise ValueError(
                        f"{type(self)} requires the 'openapi' field "
                        "or an 'oasversion' constructor parameter",
                    )

                # Chop off patch version number
                # Assign through property for version check.
                self.oasversion = '.'.join(
                    self.data['openapi'].split('.')[:2],
                )
        return self._oasversion

    @oasversion.setter
    def oasversion(self, oasversion: str) -> None:
        if oasversion not in OASCatalog.SUPPORTED_OAS_VERSIONS:
            raise OASUnsupportedVersionError(
                oasversion, uri=self.uri, url=self.url,
            )

        if (
            'openapi' in self.data and
            not (actual := self.data['openapi']).startswith(oasversion)
        ):
            raise OASVersionConflictError(
                document_version=actual,
                attempted_version=oasversion,
                uri=self.uri,
                url=self.url,
            )

        if (
            self is not self.document_root and
            oasversion != (actual := self.document_root.oasversion)
        ):
            raise OASVersionConflictError(
                document_version=actual,
                attempted_version=oasversion,
                uri=self.uri,
                url=self.url,
            )

        self._oasversion = oasversion

    @property
    def url(self) -> Optional[jschon.URI]:
        return self._url

    @url.setter
    def url(self, url -> Optional[jschon.URI]) -> None:
        self._url = url

    @property
    def sourcemap(self) -> Optional[dict]:
        """Line and column number sourcemap, if enabled."""
        return (
            self._sourcemap if self is self.document_root
            else self.document_root._sourcemap
        )

    @sourcemap.setter
    def sourcemap(self, sourcemap: Optional[dict]) -> None:
        self._sourcemap = sourcemap


class OASJSONValidationError(ValueError):
    def __init__(self, error_detail):
        super().__init__('JSON Schema validation of OAS document failed!')

    @property
    def error_detail(self):
        return self.args[1]


class OASJSON(JSONSchemaContainer, OASJSONMixin):
    """
    Representation of an OAS-complaint API document.

    Based on and derived from :class:`jschon.json.JSON`

    :param uri: The identifier of this document, used for resolving references
    :param url: The locator of this document, from which it was loaded
    :param parent: The parent :class:`jschon.json.JSON` instance, if any
    :param key: The keyword under which this object appears in the parent
    :param itemclass: The class to use to instantiate child objects
    :param catalog:
    :param cacheid:
    :param oasversion: *[in `itemkwargs`]* The
    """

    _SCHEMA_PATH_REGEX = re.compile(
        r'(/components/schemas/[^/]*)|'
        r'(/paths/[^/]*/parameters/\d+/schema)|'
        r'(/paths/[^/]*/parameters/\d+/content/[^/]*/schema)|'
        r'(/paths/[^/]*/requestBody/content/[^/]*/schema)|'
        r'(/paths/[^/]*/responses/((default)|([1-5][0-9X][0-9X])/content/[^/]*/schema)',
    )

    _uri_cls: ClassVar[Type[rid.IriReference]] = rid.IriReference
    _catalog_cls: ClassVar[Type[OASCatalog]]

    @classmethod
    def _set_catalog_cls(cls, catalog_cls):
        from oascomply.oascatalog import OASCatalog
        cls._catalog_cls = OASCatalog

    def __init__(
        self,
        value,
        *,
        uri=None,
        url=None,
        parent=None,
        key=None,
        oasversion=None,
        sourcemap=None,
        itemclass=None,
        catalog='oascomply',
        **itemkwargs,
    ):
        logger.info(
            f'{id(self)} == OASJSON({{...}}, uri={str(uri)!r}, url={str(url)!r}, '
            f'parent={None if parent is None else id(parent)}, '
            f'key={key}, itemclass={itemclass}, catalog={catalog}, '
            f'cacheid={cacheid}, ...)',
        )

        # TODO: Move to where we can check root-ness?
        if oasversion is not None:
            self.oasversion = oasversion
        self.sourcemap = sourcemap


        if itemclass is None:
            itemclass = type(self)

        self._handle_root(value, parent, oasversion, sourcemap, itemkwargs)

        if not isinstance(catalog, self._catalog_cls):
            catalog = self._catalog_cls.get_catalog(catalog)

        # Use the X.Y oasversion as the cacheid
        # TODO: Is cacheid still needed in the __init__ arg list?  Maybe to
        #       keep it out of itemkwargs as we bounce through jschon code?
        cacheid = self.oasversion

        super().__init__(
            value,
            parent=parent,
            key=key,
            uri=uri,
            itemclass=itemclass,
            **itemkwargs,
        )

    def _get_itemclass(self, ptr):
        if self._SCHEMA_PATH_REGEX.fullmatch(str(ptr)):
            return JSONSchema
        return type(self)

    def instantiate_mapping(self, value):
        itemclass = self._get_itemclass(
            self.path / k,
        )
        return {
            k: itemclass(
                parent=self,
                key=k,
                **self.itemkwargs,
            ) for k, v in value.items()
        }

    def resolve_references(self) -> None:
        if self.references_resolved == True:
            return
        result = self.validate()
        if not result.valid:
            raise OASJSONValidationError(
                result.output('detailed'),
            )

        # TODO: Filter annotations - standard and extension
        self._annotations = [
            Annotation(
                unit,
                instance_base=self.uri.copy(fragment=None))result.output('basic')

    # TODO: why is itemkwargs not self._itemkwargs yet?
    def _handle_root(
        self,
        value,
        parent,
        oasversion,
        sourcemap,
        itemkwargs,
    ):
        # NOTE: we may be in the process of construcing the parent
        #       because of how jschon.JSON tree-building works, which
        #       means bool(parent) could fail.  Instead, compare to None.
        if parent is not None:
            self.oasversion = self.document_root.oasversion
            self.sourcemap = self.document_root.sourcemap
            self._oas_metaschema_uri = self.document_root._oas_metaschema_uri
        else:
            self.document_root = self

            if oasversion is None:
                if 'openapi' not in value:
                    raise ValueError(
                        f"{type(self)} requires the 'openapi' field "
                        "or an 'oasversion' constructor parameter",
                    )

                # Chop off patch version number
                oasversion = '.'.join(value['openapi'].split('.')[:2])

            self.oasversion = oasversion

            self.sourcemap = sourcemap

            self._determine_metaschema(value)

    def _determine_metaschema(self, value):
        if self.oasversion == '3.1':
            self._oas_metaschema_uri = URI(value.get(
                'jsonSchemaDialect',
                "https://spec.openapis.org/oas/3.1/dialect/base",
            ))
        elif self.oasversion == '3.0':
            self._oas_metaschema_uri = URI(
                "https://spec.openapis.org/oas/v3.0/dialect/base",
            )
        else:
            raise OASUnsupportedVersionError(value['openapi'])

    def _determine_uri_and_url(self, parent, uri, url, key):
        # TODO: There's more URI shenanigans later in __init__
        #       related to confusion over no vs empty string fragments
        if uri is None:
            self.uri = parent.uri.copy(
                fragment=(
                    rid.JsonPtr(parent.uri.fragment) / key
                ).uri_fragment()
            )
        elif isinstance(uri, rid.UriWithJsonPtr):
            self.uri = uri
        else:
            self.uri = rid.UriWithJsonPtr(str(uri))

        if url is None:
            self.url = parent.url.copy(
                fragment=(
                    rid.JsonPtr(parent.url.fragment) / key
                ).url_fragment()
            )
        elif isinstance(url, rid.IriWithJsonPtr):
            self.url = url
        else:
            logger.debug(type(url).__name__)
            logger.debug(str(url))
            self.url = rid.UriWithJsonPtr(str(url))

    def get_annotations(
        self,
        name: Optional[str] = None,
        value: Optional[str] = None,
        instance_location: Optional[jschon.JSONPointer] = None,
        schema_location: Optional[jschon.URI] = None,
        evaluation_path: Optional[jschon.JSONPointer] = None,
        single: bool = False
        required: bool = False
    ) -> Optional[Union[Annotation, Sequence[Annotation]]]:
        """
        """
        if self._annotations is None:
            self.validate()

        annotations = [
            a for a in self._annotations
            if (
                (name is None or name == a.keyword) and
                (value is None or value == a.value) and
                (
                    instance_location is None or
                    instance_location == a.location.instance_ptr
                ) and (
                    schema_location is None or
                    schema_location == a.location.schema_uri
                ) and (
                    evaluation_path is None or
                    evaluation_path == a.location.evaluation_path_ptr
                )
            )
        ]
        if required and not annotations:
            raise ValueError("No annotations matched!")
        if single:
            if len(annotations) > 1:
                raise ValueError("Multiple annotations matched!")
            return annotations[0] if annotations else None
        return annotations

    def metaschema_uri(self) -> Optional[jschon.URI]:
        """The OAS format schema for this document node.

        Only document nodes with an ``oastype`` annotation have
        metaschemas (see :class:`OASJSONSchema` for special handling
        for Schema Objects).
        """
        if self._metaschema_uri is not None:
            return self._metaschema_uri
         
        self._metaschema_uri = self.get_annotation(
            name='oastype',
            instance_location=self.path,
            single=True,
        ).
        elif self.oasversion == '3.0':
            return self._uri_cls(OAS30_DIALECT_METASCHEMA)
        elif self.oasversion == '3.1':
            return self._uri_cls(self.data.get(
                'jsonSchemaDialect',
                "https://spec.openapis.org/oas/3.1/dialect/base",
            ))
        else:
            raise ValueError(
                f"Unsupported OAS version {self.oasversion}",
            )


class OASJSONSchema(JSONSchemaContainer, OASJSONMixin):
    @classmethod
    def _set_catalog_cls(cls):
        cls._catalog_class = OASCatalog

    @property
    def oasversion(self) -> str:
        return self.document_root.oasversion

    @property
    def metaschema_uri(self) -> Optional[jschon.URI]:
        if (m := super().metaschema_uri) is not None:
            return m
        elif self.oasversion == '3.0':
            return self._uri_cls(OAS30_DIALECT_METASCHEMA)
        elif self.oasversion == '3.1':
            return self._uri_cls(self.data.get(
                'jsonSchemaDialect',
                "https://spec.openapis.org/oas/3.1/dialect/base",
            ))
        else:
            raise ValueError(
                f"Unsupported OAS version {self.oasversion}",
            )
