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
from jschon.exc import CatalogError
from jschon.catalog import Catalog, Source, LocalSource, RemoteSource

import yaml
import rfc3339
import rfc3987
import json_source_map as jmap
import yaml_source_map as ymap
from yaml_source_map.errors import InvalidYamlError

from oascomply import resourceid as rid
from oascomply.ptrtemplates import (
    JSON_POINTER_TEMPLATE, RELATIVE_JSON_POINTER_TEMPLATE,
    RelJsonPtrTemplate,
)

__all__ = [
    'OASCatalog',
    'OASJSON',
    'DirectMapSource',
    'FileMultiSuffixSource',
    'HttpMultiSuffixSource',
]

logger = logging.getLogger(__name__)


PathString = str
Suffix = str
Content = str

@dataclass(frozen=True)
class LoadedContent:
    content: str
    url: URIString
    parse_type: str


@dataclass(frozen=True)
class ParsedContent:
    value: jschon.JSONCompatible
    url: URIString
    sourcemap: Union[dict, None]


class ResourceLoader:
    @classmethod
    def load(cls, location: str) -> LoadedContent:
        raise NotImplementedError


class FileLoader(ResourceLoader):
    @classmethod
    def load(cls, full_path: PathString) -> LoadedContent:
        """Load a file, returning the contents and the retrieval URL"""
        path = pathlib.Path(full_path)
        try:
            content = path.read_text(encoding='utf-8')
            parse_type = None
            if path.suffix in ContentParser.SUPPORTED_SUFFIXES:
                parse_type = path.suffix

            return LoadedContent(
                content=content,
                url=path.as_uri(),
                parse_type=parse_type,
            )

        except OSError as e:
            msg = f'Could not load {full_path!r}: '
            if e.filename is not None:
                # The filename for OSError is not included in
                # the exception args, apparently for historical reasons.
                raise CatalogError(
                    msg + f'{e.strerror}: {e.filename!r}',
                ) from e
            raise CatalogError(msg) from e


class HttpLoader(ResourceLoader):
    @classmethod
    def load(cls, url: URIString) -> LoadedContent:
        raise NotImplementedError


class ContentParser:
    SUPPORTED_SUFFIXES = ('.json', '.yaml', '.yml')
    """Suffixes for which we have parsers, when a media type is unavailable"""

    @classmethod
    def parse_map(cls):
        """Map of file suffixes and media types to parsing functions."""
        return {
            None: cls._unknown_parse,
            'application/json': cls._json_parse,
            'application/openapi+json': cls._json_parse,
            'application/schema+json': cls._json_parse,
            'application/*+json': cls._json_parse,
            'application/yaml': cls._yaml_parse,
            'application/openapi+yaml': cls._yaml_parse,
            'application/schema+yaml': cls._yaml_parse,
            'application/*+yaml': cls._yaml_parse,
            '': cls._unknown_parse,
            '.json': cls._json_parse,
            '.yaml': cls._yaml_parse,
            '.yml': cls._yaml_parse,
        }

    def __init__(self, loaders: Tuple[ResourceLoader]):
        self._loaders = loaders

    def _json_parse(
        self,
        full_path: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        """Load a JSON file, optionally with source line and column map."""
        sourcemap = None
        loaded = self.load(full_path)
        try:
            data = jschon.utils.json_loads(loaded.content)
            if create_source_map:
                logger.info(
                    f'Creating JSON sourcemap for {path}, '
                    '(can disable with -n if slow)',
                )
                sourcemap = jmap.calculate(content)
            return ParsedContent(value=data, url=url, sourcemap=sourcemap)
        except json.JSONDecodeError as e:
            raise CatalogError(str(e)) from e

    @classmethod
    def _yaml_parse(
        self,
        full_path: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        """Load a YAML file, optionally with source line and column map."""
        sourcemap = None
        logger.info(f"Loading {full_path} as YAML...")
        loaded = self.load(full_path)
        try:
            data = yaml.safe_load(loaded.content)
            if create_source_map:
                try:
                    logger.info(
                        f'Creating YAML sourcemap for {path}, '
                        '(can disable with -n if slow)',
                    )
                    sourcemap = ymap.calculate(content)
                except InvalidYamlError:
                    # The YAML source mapper gets confused sometimes,
                    # even with YAML that parses correctly,
                    # so just log a warning and work without the map.
                    logger.warn(
                        f"Unable to calculate source map for {path}",
                    )
            return ParsedContent(value=data, url=url, sourcemap=sourcemap)
        except InvalidYamlError:
            raise CatalogError(str(e)) from e

    @classmethod
    def _unknown_parse(
        self,
        full_path: str,
        create_source_map: bool = False,
    ) -> ParsedContent:
        """
        Load a file of unknown type by trying first JSON then YAML.
        """
        try:
            return self._json_parse(full_path, create_source_map)
        except CatalogError as e1:
            logger.warning(
                f"Failed to parse file {full_path} of unknown type "
                f"as JSON:\n\t{e1}",
            )
            try:
                return self._yaml_parse(full_path, create_source_map)
            except CatalogError as e2:
                logger.warning(
                    f"Failed to parse file {full_path} of unknown type "
                    f"as YAML:\n\t{e2}",
                )
                raise CatalogError(
                    "Could not determine content type of '{full_path}'",
                )

    @classmethod
    def load(self, location: str) -> LoadedContent:
        errors = []
        for loader in self._loaders:
            try:
                return loader.load(full_path, create_source_map)
            except CatalogError as e:
                errors.append(e)

        if len(errors) == 1:
            raise errors[e]

        # TODO: This could be better
        raise CatalogError(
            f'Could not load from {location!r}, errors:\n\t' +
            '\n\t'.join([str(err) for err in errors]),
        )


class OASSource:
    """
    Source that tracks loading information and uses modular parsers/loaders.

    The :class:`jschon.catalog.Catalog` interface does not provide
    a way to pass extra information back with a loaded document,
    or to the :clas:`jschon.jsonschema.JSONSchema` constructor when
    loading schemas.

    This class is for use with :class:`OASCatalog`, which uses
    it's properties to register data structures for storing such
    information under each resource's lookup URI.  It is assumed
    that the data structures are shared across all :class:`OASSource`
    instances within an :class:`OASCatalog`.

    Additionally, it defers the actual loading and parsing of resources
    to a modular system that handles different I/O channels and data formats.
    """

    # TODO: Maybe the maps are class attributes?

    def __init__(
        self,
        parser: ContentParser,
        **kwargs,
    ) -> None:
        self._parser = parser
        super().__init__(**kwargs)

    def set_uri_url_map(self, mapping: Mapping[URIString, URIString]):
        self._uri_url_map = mapping

    def set_uri_sourcemap_map(self, mapping: Optional[dict]) -> None:
        self._uri_sourcemap_map = mapping

    def map_url(
        self,
        relative_path: URIReferenceString,
        url: URIString,
    ) -> None:
        self._uri_url_map[self._uri_prefix + relative_path] = url

    def map_sourcemap(
        self,
        relative_path: URIReferenceString,
        sourcemap: Optional[dict],
    ) -> None:
        self._uri_sourcemap_map[self._uri_prefix + relative_path] = sourcemap

    def get_url(self, uri: URIString) -> Mapping[URIString, URIString]:
        return self._uri_url_map

    def get_sourcemap(
        self,
        uri: URIString,
    ) -> Mapping[URIString, Optional[dict]]:
        return self._uri_sourcemap_map

    @property
    def base_uri(self) -> URIString:
        """The base URI / URI prefix under which this source is registered."""
        return self._base_uri

    def set_base_uri(self, base_uri: URIString) -> None:
        self._uri_prefix = '' if base_uri is None else base_uri

    def resolve_resource(
        self,
        relative_path: URIReferenceString,
    ) -> ParsedContent:
        raise NotImplementedError

    def __call__(self, relative_path: str):
        content = self.resolve_resource(relative_path)
        self.map_url(relative_path, content.url)
        self.map_sourcemap(relative_path, content.sourcemap)
        return content.data


class MultiSuffixSource(OASSource, ContentParser):
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
        prefix: str,
        *,
        parser: ContentParser,
        suffixes: Sequence[Suffix] = ('', '.json', '.yaml'),
        **kwargs,
    ) -> None:

        self._prefix = self.validate_prefix(prefix)
        self._suffixes: Sequence[Suffix] = suffixes
        """The suffixes to search, in order."""

        super().__init__(parser=parser, **kwargs)

    @property
    def prefix(self) -> URIStringReference:
        return self._prefix

    def _validate_prefix(self, prefix: str) -> str:
        """
        Validates, normalizes, and returns the prefix.

        By default, returns the prefix as is. Subclasses should override
        as needed.
        """
        return prefix

    def resolve_resource(
        self,
        relative_path: URIReferenceString,
    ) -> ParsedContent:
        """
        Appends each suffix in turn, and attempts to load using the map.

        :returns: A tuple of the loaded data followed by the URL from
            which it was loaded.
        :raise jschon.exc.CatalogError: if no suffix could be loaded
            successfully.
        """
        no_suffix_path = self.prefix + relative_path

        for suffix in self._suffixes:
            if suffix not in self._parser.suffix_map:
                logger.debug(
                    f'suffix {suffix} for {no_suffix_path} not in suffix map'
                )
                continue

            full_path = no_suffix_path + suffix
            try:
                return self._parser.suffix_map()[suffix](full_path)

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


class FileMultiSuffixSource(MultiSuffixSource, FileLoader):
    def _validate_prefix(self, prefix: str) -> str:
        resource_dir = pathlib.Path(prefix).resolve()
        if not resource_dir.is_dir():
            raise ValueError(f'{prefix!r} must be an existing directory!')
        return f'{resource_dir}/'

    @classmethod
    def get_loaders(self) -> Sequence[ResourceLoader]:
        return (FileLoader,)


class HttpMultiSuffixSource(MultiSuffixSource, HttpLoader):
    def _validate_prefix(self, prefix: str) -> str:
        parsed_prefix = rid.Iri(prefix)
        if not parsed_prefix.path.endswith('/'):
            raise ValueError(f'{prefix!r} must contain a path ending with "/"')

        return str(parsed_prefix)

    @classmethod
    def get_loaders(self) -> Sequence[ResourceLoader]:
        return (HttpLoader,)


class DirectMapSource(OASSource, ContentParser):
    """Source for loading URIs with known exact locations."""
    def __init__(
        self,
        location_map: Mapping[URIString, str],
        *,
        parser: ContentParser,
        suffixes=(), # TODO: empty tuple not really right
        **kwargs,
    ) -> None:
        super().__init__(parser=parser, **kwargs)
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


    @classmethod
    def get_loaders(self) -> Sequence[ResourceLoader]:
        return (FileLoader, HttpLoader)


class OASCatalog(Catalog):
    SUPPORTED_OAS_VERSIONS = ('3.0', '3.1')

    def __init__(self, *args, **kwargs):
        self._uri_url_map = {}
        self._uri_sourcemap_map = {}
        super().__init__(*args, **kwargs)

    def add_uri_source(
        self,
        base_uri: Optional[rid.AnyURI],
        source: OASSource,
    ) -> None:
        # This "base URI" is really treated as a prefix, which
        # is why a value of '' works at all.
        uri_prefix = jschon.URI('' if base_uri is None else str(base_uri))
        source.set_uri_prefix(uri_prefix)
        super().add_uri_source(uri_prefix, source)

    def get_resource(
        self,
        uri: rid.AnyURIReference,
        *,
        resourceclass: Type[jschon.JSON] = None,
        metaschema_uri: rid.AnyURIReference = None,
        cacheid: str = 'default',
    ):
        if resourceclass is None:
            resourceclass = OASJSON

        jschon_uri: jschon.URI = jschon.URI(str(uri))
        jschon_metaschema_uri: jschon.URI = (
            None if metaschema_uri is None
            else jschon.URI(str(metaschema_uri))
        )

        try:
            logger.debug(
                f"Checking cache {cacheid} for resource '{jschon_uri}'",
            )
            return self._schema_cache[cacheid][jschon_uri]
        except KeyError:
            logger.debug(
                f"Resource '{jschon_uri}' not found in cache {cacheid}",
            )
            pass

        resource: Union[OASJSON, JSONSchema] = None
        jschon_base_uri: jschon.URI = None

        if jschon_uri.fragment is not None:
            jschon_base_uri = jschon_uri.copy(fragment=None)
            try:
                logger.debug(
                    f"Checking cache {cacheid} for base '{jschon_base_uri}'",
                )
                resource = self._schema_cache[cacheid][jschon_base_uri]
            except KeyError:
                pass
        else:
            jschon_base_uri = jschon_uri

        if resource is None:
            logger.debug(f"Attempting to load '{jschon_base_uri}'")

            # Note that the loading is done by the Source class, which can
            # load non-JSON sources despite the name load_json()
            data = self.load_json(jschon_base_uri)

            oasv = data.get('openapi')
            if oasv:
                short_version = oasv[:3]
                if short_version not in self.OAS_SUPPORTED_VERSIONS:
                    raise ValueError(f'Unsupported OAS version {oasv!r}')
                if short_version != cacheid:
                    raise CatalogError(
                        f'Found OAS version {oasv} in <{uri}> '
                        f'but given cache identifier {cacheid!r}',
                    )

                logger.debug(
                    f"Caching <{uri}> under {cacheid!r} matching 'openapi' "
                    "version field",
                )
            else:
                logger.debug(
                    f"No OAS version found in <{uri}>, caching under "
                    f"{cacheid!r}",
                )

            url = OASSource.get_url(jschon_base_uri)
            logger.debug(f"Resolved URI <{jschon_base_uri}> via URL <{url}>")

            # TODO: Can we end up with non-OASJSON but with an OAS cacheid,
            #       or OASJSON without one?  What do?
            kwargs = {}
            if (
                issubclass(resourceclass, jschon.JSONSchema) and
                jschon_metaschema_uri is not None
            ):
                # If we pass metaschema_uri to other classes,
                # things get confusing between it showing up in itemkwargs
                # vs being determined by OAS information
                #
                # TODO: Do we even ever load JSON Schemas with get_resource()?
                kwargs['metaschema_uri'] = jschon_metaschema_uri

            resource = resourceclass(
                doc,
                catalog=self,
                cacheid=cacheid,
                oasversion=cacheid, # TODO: too much of an assumption?
                uri=jschon_base_uri,
                url=url,
                sourcemap=self._uri_sourcemap_map[jschon_base_uri],
                **kwargs,
            )
            try:
                logger.debug(f"Re-checking cache for '{jschon_uri}'")
                return self._schema_cache[cacheid][jschon_uri]
            except KeyError:
                logger.debug(
                    f"'{uri}' not in cache, checking JSON Pointer fragment",
                )

        if jschon_uri.fragment:
            try:
                ptr = rid.JsonPtr.parse_uri_fragment(jschon_uri.fragment)
                resource = ptr.evaluate(resource)
            except rid.JsonPtrError as e:
                raise CatalogError(f"Schema not found for {jschon_uri}") from e

        # TODO: Check OASJSON-ness?  Or will this sometimes be JSONSchema??
        return resource

    def get_schema(
            self,
            uri: rid.Iri,
            *,
            metaschema_uri: rid.Iri = None,
            cacheid: Hashable = 'default',
    ) -> jschon.JSONSchema:
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
                return jschon.JSONSchema(
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


class OASJSON(jschon.JSON):
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
    def get_oas_root(cls, document: jschon.JSON):
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
        elif isinstance(document, jschon.JSONSchema):
            schema_root = document.document_schemaroot
            if schema_root.parent:
                assert isinstance(schema_root.parent, OASJSON), \
                    f'Expected OASJSON, got {type(document).__name__}'
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
            f'{id(self)} == OASJSON({{...}}, uri={str(uri)!r}, url={str(url)!r}, '
            f'parent={None if parent is None else id(parent)}, '
            f'key={key}, itemclass={itemclass}, catalog={catalog}, '
            f'cacheid={cacheid}, ...)',
        )

        self.document_root: Type[jschon.JSON]
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
        if not isinstance(self.data[key], jschon.JSONSchema):
            # TODO: Figure out jschon.URI vs rid.Uri*
            # TODO: .value vs .data
            self.data[key] = jschon.JSONSchema(
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
