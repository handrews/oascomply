from __future__ import annotations

import re
import logging
import pathlib
from os import PathLike
from collections import defaultdict
from typing import Hashable, Mapping, Optional, Sequence, Tuple, Type, Union
import json

from jschon import JSON, JSONCompatible, JSONSchema, Result, URI
from jschon.exc import CatalogError
from jschon.catalog import Catalog, Source, LocalSource, RemoteSource
from jschon.jsonpointer import RelativeJSONPointer
from jschon.vocabulary.format import format_validator
from jschon.vocabulary import (
    Keyword, KeywordClass, Metaschema, ObjectOfSubschemas, Subschema,
    Vocabulary, format as format_, annotation, applicator, validation,
)
import jschon.utils

import yaml
import rfc3339
import rfc3987
import json_source_map as jmap
import yaml_source_map as ymap
from yaml_source_map.errors import InvalidYamlError

from oascomply.ptrtemplates import (
    JSON_POINTER_TEMPLATE, RELATIVE_JSON_POINTER_TEMPLATE,
    RelJsonPtrTemplate,
)
import oascomply.resourceid as rid

__all__ = [
    'OasCatalog',
    'OasJson',
    'MultiDirectMapSource',
    'FileDirectMapSource',
    'HttpDirectMapSource',
    'FileMultiSuffixSource',
    'HttpMultiSuffixSource',
]

logger = logging.getLogger(__name__)


PathString = str
URIString = str
URIReferenceString = str
Suffix = str
Content = str
ContentWithUrlAndFormat = Tuple[
    Content,
    rid.Iri,
    str,
]

JSONCompatibleWithURLAndSourceMap = Tuple[
    JSONCompatible,
    rid.Iri,
    Union[dict, None],
]


class ResourceContentMixin:
    @classmethod
    def _load(cls, location: str):
        raise NotImplementedError


class FileContentMixin(ResourceContentMixin):
    @classmethod
    def _load(cls, full_path: PathString) -> Tuple[Content, rid.Iri]:
        """Load a file, returning the contents and the retrieval URL"""
        path = pathlib.Path(full_path)
        try:
            content = path.read_text(encoding='utf-8')
            return content, rid.Iri(path.as_uri())
        except OSError as e:
            msg = f'Could not load {full_path!r}: '
            if e.filename is not None:
                # The filename for OSError is not included in
                # the exception args, apparently for historical reasons.
                raise CatalogError(
                    msg + f'{e.strerror}: {e.filename!r}',
                ) from e
            raise CatalogError(msg) from e


class HttpContentMixin(ResourceContentMixin):
    @classmethod
    def _load(cls, url: URIString) -> Tuple[Content, rid.Iri]:
        raise NotImplementedError


class ParseDataMixin:
    @classmethod
    def content_map(cls):
        return {
            None: cls._unknown_parse,
            'application/json': cls._json_parse,
            'application/openapi+json': cls._json_parse,
            'application/schema+json': cls._json_parse,
            'application/*+json': cls._json_parse,
            'application/yaml': cls._yaml_parse,
            'application/openapi+yaml': cls._yaml_parse,
            'application/schema+yaml': cls._yaml_parse,
            'application/*+yaml': cls._yaml_parse
        }

    @classmethod
    def suffix_map(cls):
        """Map of suffixes to callables for loading matching URIs."""
        return {
            '': cls._unknown_parse,
            '.json': cls._json_parse,
            '.yaml': cls._yaml_parse,
            '.yml': cls._yaml_parse,
        }

    @classmethod
    def _json_parse(
        cls,
        full_path: str,
        create_source_map: bool = False,
    ) -> JSONCompatibleWithURLAndSourceMap:
        """Load a JSON file, optionally with source line and column map."""
        sourcemap = None
        content, url = cls._load(full_path)
        try:
            data = jschon.utils.json_loads(content)
            if create_source_map:
                logger.info(
                    f'Creating JSON sourcemap for {path}, '
                    '(can disable with -n if slow)',
                )
                sourcemap = jmap.calculate(content)
            return data, url, sourcemap
        except json.JSONDecodeError as e:
            raise CatalogError(str(e)) from e

    @classmethod
    def _yaml_parse(
        cls,
        full_path: str,
        create_source_map: bool = False,
    ) -> JSONCompatibleWithURLAndSourceMap:
        """Load a YAML file, optionally with source line and column map."""
        sourcemap = None
        logger.info(f"Loading {full_path} as YAML...")
        content, url = cls._load(full_path)
        try:
            data = yaml.safe_load(content)
            if create_source_map:
                # The YAML source mapper gets confused sometimes,
                # so just log a warning and work without the map.
                try:
                    logger.info(
                        f'Creating YAML sourcemap for {path}, '
                        '(can disable with -n if slow)',
                    )
                    sourcemap = ymap.calculate(content)
                except InvalidYamlError:
                    logger.warn(
                        f"Unable to calculate source map for {path}",
                    )
            return data, url, sourcemap
        except InvalidYamlError:
            raise CatalogError(str(e)) from e

    @classmethod
    def _unknown_parse(
        cls,
        full_path: str,
        create_source_map: bool = False,
    ) -> JSONCompatibleWithURLAndSourceMap:
        """
        Load a file of unknown type by trying first JSON then YAML.
        """
        try:
            return _json_parse(full_path, create_source_map)
        except CatalogError as e1:
            logger.warning(
                f"Failed to parse file {full_path} of unknown type "
                f"as JSON:\n\t{e1}",
            )
            try:
                return _yaml_parse(full_path, create_source_map)
            except CatalogError as e2:
                logger.warning(
                    f"Failed to parse file {full_path} of unknown type "
                    f"as YAML:\n\t{e2}",
                )
                raise CatalogError(
                    "Could not determine content type of '{full_path}'",
                )


class UrlAndSourceMapMixin:
    """
    Mixin for registering a shared map of URIs to other information.
    Allows setting and reading a shared URI to URL map for external use.

    The :class:`jschon.catalog.Catalog` interface does not allow returning
    additional information with the resource data.  This class allows
    registering dictionaries shared across a catalog's sources where
    extra information (specifically the URL and optional source line and
    column number map) can be stored for later easy lookup.  This information
    is needed by :class:`OasJson`.

    This also requires a property for the base URI under which the source
    is registered in the catalog, in order to properly construct the
    URI for use in the map, as only using relative URIs would cause
    conflicts within the map when the same relative path might be used
    with different sourcdes.
    """
    @property
    def uri_url_map(self) -> Mapping[rid.Iri, rid.Iri]:
        """A map from requested URI to located URL, shared among sources"""
        return self._uri_url_map

    @uri_url_map.setter
    def uri_url_map(self, mapping: Mapping[rid.Iri, rid.Iri]):
        self._uri_url_map = mapping

    @property
    def uri_sourcemap_map(self) -> Mapping[rid.Iri, Optional[dict]]:
        """A map from requested URI to source line/column number maps"""
        return self._uri_sourcemap_map

    @uri_sourcemap_map.setter
    def uri_sourcemap_map(self, mapping: Optional[dict]) -> None:
        self._uri_sourcemap_map = mapping

    @property
    def base_uri(self) -> URIString:
        """The base URI / URI prefix under which this source is registered."""
        return self._base_uri

    @base_uri.setter
    def base_uri(self, bu: URIString) -> None:
        self._base_uri = '' if bu is None else bu


class MultiSuffixSource(Source, ParseDataMixin, UrlAndSourceMapMixin):
    """
    Source that appends each of a list of suffixes before attempting to load.

    Subclasses are expected to map an appropriate callable to each supported
    suffix, which can include an empty string for un-suffixed locations.
    Non-empty suffixes MUST include any leading ``.`` character that
    would not be present in the requested URI.

    The content is returned from the first suffix that can be loaded
    successfully.

    :param suffixes: The list of suffixes to search in order.
    """
    def __init__(
        self,
        prefix: str,  # TODO: only include in sublcass init?
        *,
        suffixes: Sequence[Suffix] = ('', '.json', '.yaml'),
        **kwargs,
    ) -> None:
        self._suffixes: Sequence[Suffix] = suffixes
        """The suffixes to search, in order."""

        super().__init__(**kwargs)

    @property
    def prefix(self) -> str:
        """The prefix (e.g. directory or URL prefix) for relative paths)"""
        return self._prefix

    @prefix.setter
    def prefix(self, p: str) -> None:
        self._prefix = p

    def _search_suffixes(
        self,
        no_suffix_path: URIReferenceString,
    ) -> JSONCompatibleWithURLAndSourceMap:
        """
        Appends each suffix in turn, and attempts to load using the map.

        :returns: A tuple of the loaded data followed by the URL from
            which it was loaded.
        :raise jschon.exc.CatalogError: if no suffix could be loaded
            successfully.
        """
        for suffix in self._suffixes:
            if suffix not in self._suffixes:
                logger.debug(
                    f'suffix {suffix} for {no_suffix_path} not in suffix map'
                )
                continue

            full_path = no_suffix_path + suffix
            try:
                return self.suffix_map()[suffix](full_path)

            except CatalogError as e:
                # TODO: Ideally not base Exception, but conditional import
                #       of requests for remote source is challenging
                logger.debug(
                    f"Checked {self.base_dir!r} for {relative_path!r}, "
                    f"got exception:\n\t{e}"
                )
        raise CatalogError(
            f"Could not find '{no_suffix_path}', "
            f"checked extensions {self._suffixes}"
        )

    def __call__(self, relative_path: str):
        data, url, sourcemap = self._search_suffixes(relative_path)
        self.uri_url_map[relative_path] = url
        self.uri_sourcemap_map[relative_path] = sourcemap
        return data


class DirectMapSource(Source, ParseDataMixin, UrlAndSourceMapMixin):
    """Source for loading URIs with known exact locations."""
    def __init__(
        self,
        location_map: Mapping[URIString, str],
        *,
        suffixes=(), # TODO: empty tuple not really right
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._suffixes = suffixes
        self._map = location_map.copy()

    def __call__(self, relative_path: str):
        if (location := self._map.get(relative_path)) is None:
            raise CatalogError(f'Requested unkown resource {relative_path!r}')

        for suffix in self._suffixes:
            if str(location).endswith(suffix):
                data, url, sourcemap = self.suffix_map()[suffix](location)
                self.uri_url_map[relative_path] = url
                self.uri_sourcemap_map[relative_path] = sourcemap
                return data

        raise CatalogError(f'Cannot determine format of {relative_path!r}')


class MultiDirectMapSource(Source, UrlAndSourceMapMixin):
    """Allows registering multiple direct map sources under ``None``"""
    def __init__(self, sources: Tuple[Source], **kwargs):
        self._sources = sources
        super().__init__(**kwargs)

    def __call__(self, relative_path: str):
        for source in self._sources:
            try:
                return source(relative_path)
            except CatalogError as e:
                logger.debug(
                    f'Got exception "{e}" from source {type(source).__name__}'
                )

        raise CatalogError(f'Requested unkown resource {relative_path!r}')

    @property
    def uri_url_map(self) -> Mapping[rid.Iri, rid.Iri]:
        return super().uri_url_map

    @uri_url_map.setter
    def uri_url_map(self, mapping: Mapping[rid.Iri, rid.Iri]):
        self._uri_url_map = mapping
        for source in self._sources:
            source.uri_url_map = mapping

    @property
    def uri_sourcemap_map(self) -> Mapping[rid.Iri, rid.Iri]:
        return super().uri_url_map

    @uri_sourcemap_map.setter
    def uri_sourcemap_map(self, mapping: Optional[dict]) -> None:
        self._uri_sourcemap_map = mapping
        for source in self._sources:
            source.uri_sourcemap_map = mapping

    @property
    def base_uri(self) -> Mapping[rid.Iri, rid.Iri]:
        return super().uri_url_map

    @base_uri.setter
    def base_uri(self, bu: URIString) -> None:
        self._base_uri = '' if bu is None else bu
        for source in self._sources:
            source.base_uri = self._base_uri


class FileDirectMapSource(DirectMapSource, FileContentMixin):
    pass


class FileMultiSuffixSource(MultiSuffixSource, FileContentMixin):
    def __init__(
        self,
        prefix: str,
        *,
        suffixes: Sequence[Suffix] = ('', '.json', '.yaml'),
        **kwargs,
    ) -> None:
        resource_dir = pathlib.Path(prefix).resolve()
        if not resource_dir.is_dir():
            raise ValueError(f'{prefix!r} must be an existing directory!')

        self.prefix = f'{resource_dir}/'
        # TODO: omit prefix?
        super().__init__(self.prefix, suffixes=suffixes)


class HttpDirectMapSource(DirectMapSource, HttpContentMixin):
    pass


class HttpMultiSuffixSource(MultiSuffixSource, HttpContentMixin):
    def __init__(
        self,
        prefix: str,
        *,
        suffixes: Sequence[Suffix] = ('', '.json', '.yaml'),
        **kwargs,
    ) -> None:
        parsed_prefix = rid.Iri(prefix)
        if not parsed_prefix.path.endswith('/'):
            raise ValueError(f'{prefix!r} must contain a path ending with "/"')

        self.prefix = str(parsed_prefix)

        # TODO: omit prefix?
        super().__init__(self.prefix, suffixes=suffixes)


class OasCatalog(Catalog):
    def __init__(self, *args, **kwargs):
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}
        super().__init__(*args, **kwargs)

    def add_uri_source(
        self,
        base_uri: Optional[rid.Iri],
        source,  # TODO: fix types
    ) -> None:
        if base_uri is None:
            source.base_uri = '' if base_uri is None else str(base_uri)
            jschon_base_uri = None
        else:
            source.base_uri = base_uri
            # if base_uri.scheme == 'file' and base_uri.authority is None:
            #     base_uri = base_uri.copy_with(authority='')
            jschon_base_uri = URI(str(base_uri))
        source.uri_url_map = self._uri_url_map
        source.uri_sourcemap_map = self._uri_sourcemap_map

        super().add_uri_source(jschon_base_uri, source)

    def get_resource(
        self,
        uri: rid.IriReference,
        *,
        resourceclass: Type[JSON] = None,
        metaschema_uri: rid.IriReference = None,
        cacheid: str = 'default',
    ):
        if resourceclass is None:
            resourceclass = OasJson

        jschon_uri: URI = URI(str(uri))
        try:
            logger.debug(
                f"Checking cache {cacheid} for resource '{uri}'",
            )
            return self._schema_cache[cacheid][jschon_uri]
        except KeyError:
            logger.debug(
                f"Resource '{uri}' not found in cache {cacheid}",
            )
            pass

        resource = None
        base_uri: rid.Iri = uri.to_absolute()
        jschon_base_uri: URI = URI(str(base_uri))

        if uri.fragment is not None:
            try:
                logger.debug(
                    f"Checking cache {cacheid} for base '{base_uri}'",
                )
                resource = self._schema_cache[cacheid][jschon_base_uri]
            except KeyError:
                pass

        if resource is None:
            logger.debug(f"Attempting to load '{base_uri}'")

            # Note that the loading is done by the Source class, which can
            # load non-JSON sources despite the name load_json()
            doc = self.load_json(jschon_base_uri)

            if oasv := doc.get('openapi'):
                if oasv.startswith('3.0'):
                    cacheid='3.0'
                elif oasv.startswith('3.1'):
                    cacheid='3.1'
                else:
                    raise ValueError(f'Unsupported OAS version {oasv!r}')
                logger.debug(f"Caching under OAS version {cacheid}")
            else:
                logger.debug(
                    f"No OAS version found, caching under {cacheid!r}",
                )

            url = self._uri_url_map[base_uri]
            logger.debug(f"Resolve URI '{base_uri}' via URL '{url}'")

            kwargs = {}
            if (
                issubclass(resourceclass, JSONSchema) and
                metaschema_uri is not None
            ):
                # If we pass metaschema_uri to other classes,
                # things get confusing between it showing up in itemkwargs
                # vs being determined by OAS information
                #
                # TODO: Do we even ever load JSON Schemas with get_resource()?
                kwargs['metaschema_uri'] = metaschema_uri

            resource = resourceclass(
                doc,
                catalog=self,
                cacheid=cacheid,
                oasversion=cacheid, # TODO: too much of an assumption?
                uri=jschon_base_uri,
                url=url,
                sourcemap=self._uri_sourcemap_map[base_uri],
                **kwargs,
            )
            try:
                logger.debug(f"Re-checking cache for '{uri}'")
                return self._schema_cache[cacheid][uri]
            except KeyError:
                logger.debug(
                    f"'{uri}' not in cache, checking JSON Pointer fragment",
                )

        if uri.fragment:
            try:
                ptr = rid.JsonPtr.parse_uri_fragment(uri.fragment)
                resource = ptr.evaluate(resource)
            except rid.JsonPtrError as e:
                raise CatalogError(f"Schema not found for {uri}") from e

        # TODO: Check OasJson-ness?  Or will this sometimes be OasJsonSchema?
        return resource

    def get_schema(
            self,
            uri: rid.Iri,
            *,
            metaschema_uri: rid.Iri = None,
            cacheid: Hashable = 'default',
    ) -> JSONSchema:
        # TODO: metaschema_uri needs to be set based on oasversion
        #       This can be hard if loading a separate schema resource
        #       as we may not have access to the relevant "current"
        #       oasversion, which may change depending on the access
        #       path.  We may need separate 3.0 and 3.1 caches.
        try:
            logger.debug(f'META ({cacheid}): <{metaschema_uri}>')
            return super().get_schema(
                URI(str(uri)),
                metaschema_uri=URI(str(metaschema_uri)),
                cacheid=cacheid,
            )
        except CatalogError as e:
            if 'not a JSON Schema' not in str(e):
                raise

            # TODO: URI library confusion again... UGH
            base_uri = rid.Iri(uri).to_absolute()
            resource = self.get_resource(base_uri, cacheid=cacheid)
            self.del_schema(uri)

            if uri.fragment is None or uri.fragment == '':
                self.del_schema(base_uri)
                # TODO: .value vs .data
                return OasJsonSchema(
                    resource.value,
                    uri=uri,
                    metaschema_uri=metaschema_uri,
                    catalog=self,
                    cacheid=cacheid,
                )
            # TODO: should not overload rid.IriReference.fragment type
            fragment_str = str(uri.fragment)
            if not fragment_str.startswith('/'):
                raise ValueError(
                    'Non-JSON Pointer fragments not yet supported',
                )
            ptr = uri.fragment # = rid.JsonPtr.parse_uri_fragment(uri.fragment)
            parent_ptr = ptr[:-1]
            key = ptr[-1]

            parent = parent_ptr.evaluate(resource)
            logger.debug(f'DEBUGGG r: {type(resource).__name__} <{resource.uri}> p: {type(parent).__name__} <{parent.path}>')
            return parent.convert_to_schema(key)


class OasJsonSchema(JSONSchema):
    """
    :class:`JSONSchema` subclass embeddable in :class:`OasJson`

    :param parent: the parent :class:`OasJsonSchema`, if any
    :param root: the root of the containing :class:`OasJson` instance
    """
    def __init__(
            self,
            value: Union[bool, Mapping[str, JSONCompatible]],
            *,
            catalog: Union[str, Catalog] = 'catalog',
            cacheid: Hashable = 'default',
            uri: rid.Iri = None,
            metaschema_uri: rid.Iri = None,
            parent: JSON = None,
            key: str = None,
            root: Union[OasJson, OasJsonSchema] = None,
    ):
        """
        All parameters the same as for :class:`jschon.jsonschema.JSONSchema`
        unless otherwise specified.

        :param root: The :class:`jschon.json.JSON` instance at the root of
            the document; if None, then this instance is at the document root.
            It is an error to specify a parent but not a root.
        """
        super().__init__(
            value,
            catalog=catalog,
            cacheid=cacheid,
            uri=URI(str(uri)),
            metaschema_uri=URI(str(metaschema_uri)),
            parent=parent,
            key=key,
        )
        parent_root = None if parent is None else parent.document_root

        if root != parent.document_root:
            raise ValueError(
                'OasJsonSchemas in the same document must have the same '
                f'document root! Given {root} for {uri}, with '
                f'parent {parent.document_root.uri}',
            )
        if root is None and parent is not None:
            raise ValueError('Cannot be a document root if a parent is present')

        self.document_root = self if root is None else root
        """Root :class:`jschon.json.JSON` object in the document."""


class OasJson(JSON):
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

    @classmethod
    def get_oas_root(cls, document: JSON):
        """
        Find the root object for any :class:`jschon.json.JSON` document.

        Since the :package:`jschon` classes don't understand schemas
        embedded in other documents, and it is not possible to get all
        parts of ``jschon`` to instantiate subclasses where needed,
        this classmethod can be used with any :class:`jschon.json.JSON`
        subclass.
        """
        if isinstance(document, cls):
            return document.document_root
        elif isinstance(document, JSONSchema):
            schema_root = document.document_schemaroot
            if schema_root.parent:
                assert isinstance(schema_root.parent, OasJson), \
                    f'Expected OasJson, got {type(document).__name__}'
                return schema_root.parent.document_root
            return schema_root

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
        cacheid='default',
        **itemkwargs,
    ):
        logger.info(
            f'{id(self)} == OasJson({{...}}, uri={str(uri)!r}, url={str(url)!r}, '
            f'parent={None if parent is None else id(parent)}, '
            f'key={key}, itemclass={itemclass}, catalog={catalog}, '
            f'cacheid={cacheid}, ...)',
        )

        self.document_root: Type[JSON]
        """Root :class:`jschon.json.JSON` object in the document."""

        self.oasversion: str
        """The major and minor (X.Y) part of the "openapi" version string"""

        self.sourcemap: Optional[dict] = sourcemap
        """Line and column number sourcemap, if enabled."""

        if itemclass is None:
            itemclass = type(self)

        self._handle_root(value, parent, oasversion, sourcemap, itemkwargs)
        self._determine_uri_and_url(parent, uri, url, key)

        if not isinstance(catalog, Catalog):
            catalog = Catalog.get_catalog(catalog)

        # Use the X.Y oasversion as the cacheid
        # TODO: Is cacheid still needed in the __init__ arg list?  Maybe to
        #       keep it out of itemkwargs as we bounce through jschon code?
        cacheid = self.oasversion

        # Track position with JSON Pointer fragments, so ensure we have one
        # TODO: Sometimes we don't want an empty fragment on the root document.
        if not self.uri.fragment:
            if self.uri.fragment is None:
                logger.debug(f"Adding '{self.uri}' to cache '{cacheid}'")
                catalog.add_schema(URI(str(self.uri)), self, cacheid=cacheid)
                self.uri = self.uri.copy_with(fragment='')
            else:
                logger.debug(
                    f"Adding '{self.uri.to_absolute()}' to cache '{cacheid}'",
                )
                catalog.add_schema(
                    URI(str(self.uri.to_absolute())),
                    self,
                    cacheid=cacheid,
                )
        if not self.url.fragment:
            self.url = self.url.copy_with(fragment='')

        self._schemakwargs = itemkwargs.copy()
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
            self.document_root = parent.document_root
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
                oasversion = value['openapi'][:3]
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
            raise ValueError(
                f"Unsupported OAS version {value['openapi']}",
            )

    def _determine_uri_and_url(self, parent, uri, url, key):
        # TODO: There's more URI shenanigans later in __init__
        #       related to confusion over no vs empty string fragments
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
        elif isinstance(url, rid.IriWithJsonPtr):
            self.url = url
        else:
            logger.debug(type(url).__name__)
            logger.debug(str(url))
            self.url = rid.UriWithJsonPtr(str(url))

    def convert_to_schema(self, key):
        if not isinstance(self.data[key], OasJsonSchema):
            # TODO: Figure out jschon.URI vs rid.Uri*
            # TODO: .value vs .data
            self.data[key] = OasJsonSchema(
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
