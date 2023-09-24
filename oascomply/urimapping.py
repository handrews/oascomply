from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal, Optional, Sequence, Union

import jschon
import jschon.exc


__all__ = [
    'URI',
    'URIError',
    'LocationToURI',
    'PathToURI',
    'URLToURI',
]


logger = logging.getLogger(__name__)


URI: TypeAlias = jschon.URI
"""URI alias for modules that otherwise have no need for jschon."""


URIError: TypeAlias = jschon.exc.URIError
"""URI error alias for modules that otherwise have no need for jschon."""


class LocationToURI:
    """
    Helper class for mapping URIs to URLs and back.

    In addition to being more convenient than a tuple or dict, this class
    hierarchy handles calculating URIs from locations based on various factors.

    :param location: a string represenging the location; see subclasses for
        specific location types
    :param primary_uri: the URI to associate with the location; if None,
        a suitable URI will be generated based on the other parameters,
    :param additional_uris: URIs defined in the content of the resource
        at the location, but which are not URIs for that resource itself
    :param oastype: The semantic type to use to parse the resource without
        needing a reference to it first; without this parameter, resources
        are only parsed in accordance with reference usage
    :param strip_suffixes: The suffixes, if any, to strip when determining
        a URI from the location
    :param uri_is_prefix: Indicates that the URI will be used as a prefix,
        which currently requires it to have a path ending in "/".
    """
    def __init__(
        self,
        location: str,
        primary_uri: Optional[str] = None,
        *,
        additional_uris: Sequence[str] = (),
        oastype: Optional[str] = None,
        strip_suffixes: Sequence[str] = (),
        uri_is_prefix: bool = False,
    ) -> None:
        logger.debug(
            f'Parsing location+uri option with argument {location!r}, '
            f'{primary_uri!r}, additional_uris={additional_uris!r}, '
            f'oastype={oastype!r}, strip_suffixes={strip_suffixes!r}, '
            f'uri_is_prefix={uri_is_prefix!r}',
        )
        try:
            self._primary_uri = (
                None if primary_uri is None
                else URI(primary_uri)
            )
            self._auto_uri = not primary_uri
            self._additional_uris = [URI(u) for u in additional_uris]

            self._oastype = oastype

            self._to_strip = tuple(strip_suffixes)
            self._uri_is_prefix = uri_is_prefix

            location = self._set_location(location)

            if self._uri_is_prefix and self._additional_uris:
                raise ValueError(
                    'Cannot associate additional URIs with a URI prefix',
                )

            if self._primary_uri:
                uri_obj = self._primary_uri
                logger.debug(
                    f'Using URI <{uri_obj}> from command line for "{location}"'
                )
            else:
                uri_obj = self._uri_from_location(
                    self._strip_suffixes(location),
                )
                logger.debug(
                    f'Calculated URI <{uri_obj}> for "{location}"'
                )

            if uri_is_prefix and not uri_obj.path.endswith('/'):
                raise ValueError(
                    f"URI prefix <{uri_obj}> must have a path ending in '/'",
                )

            self.set_uri(uri_obj)

            if uri_is_prefix and uri_obj.query or self.uri.fragment:
                raise ValueError(
                    f"URI prefix <{self.uri}> may not include "
                    "a query or fragment",
                )

            logger.info(f'Constructed LocationToURI {self})')

        except Exception:
            # argparse suppresses any exceptions that are raised, so log them
            import traceback
            from io import StringIO

            buffer = StringIO()
            traceback.print_exc(file=buffer)
            logger.warning(buffer.getvalue())

            raise

    def __repr__(self):
        kwargs = {
            'additional_uris': [str(u) for u in self._additional_uris],
            'oastype': self._oastype,
            'strip_suffixes': self._to_strip,
            'uri_is_prefix': self._uri_is_prefix,
        }
        kwargs_str = ', '.join([f'{k!s}={v!r}' for k, v in kwargs.items()])
        return (
            f'{self.__class__.__name__}('
            f'{str(self._location)!r}, '
            f'{str(self._primary_uri)!r}, ' +
            kwargs_str +
            ')'
        )

    def __eq__(self, other):
        if not isinstance(other, LocationToURI):
            return NotImplemented
        return (
            self.location == other.location and
            self.uri == other.uri and
            self.additional_uris == other.additional_uris and
            self.oastype == other.oastype and
            self._to_strip == other._to_strip and
            self._uri_is_prefix == other._uri_is_prefix
        )

    @property
    def location(self):
        """
        Generic location accessor; subclasses should offer a more specific one.

        See non-public :meth:`_set_location` for managing modifications.
        """
        return self._location

    @property
    def oastype(self) -> Optional[str]:
        return self._oastype

    @property
    def auto_uri(self) -> bool:
        """
        True if this class generated a URI rather than receiving it as a param.
        """
        return self._auto_uri

    @property
    def additional_uris(self) -> Sequence[URI]:
        """
        Additional URIs defined in the contents of the resource at the location.
        """
        return self._additional_uris

    def __str__(self):
        return (
            f'(location: "{self.location}", uri: <{self.uri}>' +
            (')' if self.oastype is None else ', oastype: "{self.oastype}")')
        )

    def _strip_suffixes(self, location: Any) -> str:
        location_string = str(location)
        for suffix in self._to_strip:
            if suffix == '':
                return location_string
            if location_string.endswith(suffix):
                return location_string[:-len(suffix)]
        return location_string

    def _set_location(self, location_str) -> Any:
        self._location = location_str
        return location_str

    def set_uri(
        self,
        uri: URI,
        attrname: str = 'uri',
    ) -> None:
        try:
            uri.validate(require_scheme=True)
            setattr(self, attrname, (uri))
        except URIError as e:
            logger.debug(
                f'got exception from URI <{uri}>):'
                f'\n\t{e}'
            )
            raise ValueError(f'<{uri}> cannot be relative')

    def _uri_from_location(self, stripped_location_str: str) -> str:
        return URI(stripped_location_str)


class PathToURI(LocationToURI):
    """Local filesystem path to URI utility class."""

    def __str__(self):
        return (
            f'(path: "{self.path}", uri: <{self.uri}>' +
            (')' if self.oastype is None else ', oastype: "{self.oastype}")')
        )

    def _set_location(self, location_str: str) -> None:
        self.path = Path(location_str).resolve()
        self._location = self.path
        if self._uri_is_prefix and not self.path.is_dir():
            raise ValueError(
                f"Path '{self.path}' must be a directory when mapping "
                "to a URI prefix",
            )
        return self.path

    def _uri_from_location(self, stripped_location_str: str) -> str:
        # It seems odd to rebuild the path object, but Path.with_suffix('')
        # doesn't care what suffix is removed, so we couldn't use it anyway
        # Also, arg parsing code does not need to be blazingly fast.
        path = Path(stripped_location_str).resolve()

        # Technically, URI trailing slashes don't mean the same location as
        # "directory", but that is the expectation of the dir mapping code.
        uri = path.as_uri()
        if path.is_dir() and self._uri_is_prefix and not uri.endswith('/'):
            uri += '/'

        return URI(uri)

    @property
    def path(self) -> Path:
        """Accessor for the location of this LocationToURI subclass."""
        return self._path

    @path.setter
    def path(self, p: Path) -> None:
        self._path = p

    @property
    def location(self) -> Any:
        return self.path


class URLToURI(LocationToURI):
    """URL to URI utility class; does not check URL scheme or usability."""
    def __str__(self):
        return (
            f'(url: <{self.url}>, uri: <{self.uri}>' +
            (')' if self.oastype is None else ', oastype: "{self.oastype}")')
        )

    def _set_location(self, location_str: str) -> None:
        self.set_uri(URI(location_str), attrname='url')
        self._location = self.url
        if self._uri_is_prefix and not self.url.path.endswith('/'):
            raise ValueError(
                f"URL prefix <{location_str}> must have a path ending in '/'",
            )
        return self.url

    @property
    def url(self) -> URI:
        """Accessor for the location of this LocationToURI subclass."""
        return self._url

    @url.setter
    def url(self, u: URI) -> None:
        self._url = u

    @property
    def location(self):
        return self.url
