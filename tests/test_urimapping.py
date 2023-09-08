import sys
import logging
from pathlib import Path

import jschon

import pytest

from oascomply.urimapping import (
    URI,
    LocationToURI,
    PathToURI,
    URLToURI,
)


from . import (
    BASE_URI,
    FOO_YAML_URI,
    FOO_URI,
    DIR_URI,
    OTHER_URI,
    FOO_JSON_PATH,
    FOO_PATH,
    FOO_JSON_PATH_URL,
    FOO_PATH_URL,
    CURRENT_DIR,
    CURRENT_DIR_URL,
)


@pytest.mark.parametrize(
    'args,kwargs,location,uri,uris,oastype,suffixes,is_prefix', (
    (
        ['about:blank'],
        {},
        'about:blank',
        jschon.URI('about:blank'),
        [],
        None,
        (),
        False,
),
    (
        [str(FOO_YAML_URI)],
        {'strip_suffixes': ['.json'], 'oastype': 'Schema'},
        str(FOO_YAML_URI),
        FOO_YAML_URI,
        [],
        'Schema',
        ['.json'],
        False,
    ),
    (
        [str(FOO_YAML_URI)],
        {'strip_suffixes': ['.yaml'], 'oastype': 'OpenAPI'},
        str(FOO_YAML_URI),
        FOO_URI,
        [],
        'OpenAPI',
        ['.yaml'],
        False,
    ),
    (
        [str(BASE_URI)],
        {'strip_suffixes': (), 'uri_is_prefix': True },
        str(BASE_URI),
        BASE_URI,
        [],
        None,
        (),
        True,
    ),
    (
        ['foo', str(OTHER_URI)],
        {'additional_uris': [str(FOO_URI), str(FOO_PATH_URL)]},
        'foo',
        OTHER_URI,
        [FOO_URI, FOO_PATH_URL],
        None,
        (),
        False,
    ),
    (
        ['foo.yaml', str(OTHER_URI)],
        {'strip_suffixes': ['.yaml']},
        'foo.yaml',
        OTHER_URI,
        [],
        None,
        ['.yaml'],
        False,
    ),
    (
        ['foo.yaml', str(FOO_YAML_URI)],
        {'strip_suffixes': ['.yaml']},
        'foo.yaml',
        FOO_YAML_URI,
        [],
        None,
        ['.yaml'],
        False,
    ),
    (
        ['foo', str(BASE_URI)],
        {'uri_is_prefix': True},
        'foo',
        BASE_URI,
        [],
        None,
        (),
        True,
    ),
))
def test_location_to_uri(
    args, kwargs, location, uri, uris, oastype, suffixes, is_prefix):
    t = LocationToURI(*args, **kwargs)
    assert t.location == location
    assert t.uri == uri
    assert t.auto_uri == (len(args) < 2 or args[1] is None)
    assert t.additional_uris == uris
    assert t.oastype == oastype
    assert t._to_strip == suffixes
    assert t._uri_is_prefix == is_prefix


@pytest.mark.parametrize('args,kwargs,error', (
    (
        [str(FOO_YAML_URI)],
        {
            'strip_suffixes': (),
            'uri_is_prefix': True,
        },
        "must have a path ending in '/'",
    ),
    (
        ['https://ex.org/?query'],
        {
            'strip_suffixes': (),
            'uri_is_prefix': True,
        },
    "not include a query or fragment",
    ),
    (
        ['https://ex.org/#frag'],
        {
            'strip_suffixes': (),
            'uri_is_prefix': True,
        },
    "not include a query or fragment",
    ),
    (
        ['foo'],
        {},
        'cannot be relative',
    ),
    (
        ['https://ex.org'],
        {
            'additional_uris': ['https://foo.org'],
            'uri_is_prefix': True,
        },
        'Cannot associate additional URIs with a URI prefix',
    ),
))
def test_location_to_uri_errors(args, kwargs, error, caplog):
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            LocationToURI(*args, **kwargs)
    assert error in caplog.text


def test_location_to_uri_set_uri():
    t = LocationToURI('about:blank', str(FOO_YAML_URI))
    t.set_uri(FOO_URI)
    assert t.uri == FOO_URI


@pytest.mark.parametrize('args,kwargs', (
    # TODO: Test oastype, additional_uris correctly
    (['about:blank'], {}),
    (
        [str(OTHER_URI), str(BASE_URI)],
        {'strip_suffixes': ['.json'], 'uri_is_prefix': True},
    ),
))
def test_location_to_uri_repr(args, kwargs):
    t = LocationToURI(*args, **kwargs)
    repr_args = [
        args[0],
        args[1] if len(args) > 1 else str(None),
    ]
    repr_kwargs = {
        'additional_uris': [],
        'oastype': None,
        'strip_suffixes': (),
        'uri_is_prefix': False,
    }
    repr_kwargs.update(kwargs)
    repr_kwargs_str = ', '.join(
        [f'{k!s}={v!r}' for k, v in repr_kwargs.items()],
    )

    assert repr(t) == (
        f'LocationToURI('
            f'{repr_args[0]!r}, '
            f'{repr_args[1]!r}, ' +
            repr_kwargs_str +
        f')'
    )


@pytest.mark.parametrize('left,right,equal', (
    (
        LocationToURI('about:blank', str(FOO_URI)),
        LocationToURI('about:blank', str(FOO_URI)),
        True,
    ),
    (
        LocationToURI(str(OTHER_URI), str(FOO_URI)),
        LocationToURI('about:blank', str(FOO_URI)),
        False,
    ),
    (
        LocationToURI('about:blank', str(OTHER_URI)),
        LocationToURI('about:blank', str(FOO_URI)),
        False,
    ),
))
def test_location_to_uri_eq(left, right, equal):
    assert (left == right) is equal


@pytest.mark.parametrize('args,kwargs,path,uri', (
    (
        ['foo.json'],
        {
            'strip_suffixes': ['.yaml'],
        },
        FOO_JSON_PATH,
        FOO_JSON_PATH_URL,
    ),
    (
        ['foo.json'],
        {
            'strip_suffixes': ['.json'],
        },
        FOO_JSON_PATH,
        FOO_PATH_URL,
    ),
    (
        ['./'],
        {
            'strip_suffixes': ['.json'],
            'uri_is_prefix': True,
        },
        CURRENT_DIR,
        CURRENT_DIR_URL,
    ),
))
def test_path_to_uri(args, kwargs, path, uri):
    p = PathToURI(*args, **kwargs)
    assert p.path == path
    assert p.uri == uri
    assert p.location == p.path


def test_path_to_uri_str():
    assert (
        str(PathToURI(
            str(FOO_JSON_PATH),
            str(FOO_PATH_URL),
            strip_suffixes=['.json'],
        ))
        ==
        f'(path: "{FOO_JSON_PATH}", uri: <{FOO_PATH_URL}>)'
    )


def test_prefix_requires_dir(caplog):
    error = 'must be a directory'
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            PathToURI(
                'ldkjfsdfjlsfjdjfsdf',
                strip_suffixes=[],
                uri_is_prefix=True,
            )
    assert error in caplog.text


@pytest.mark.parametrize('args,kwargs,url,uri', (
    (
        [str(FOO_YAML_URI)],
        {
            'strip_suffixes': ['.json'],
        },
        FOO_YAML_URI,
        FOO_YAML_URI),
    (
        [str(BASE_URI), str(DIR_URI)],
        {
            'strip_suffixes': [],
            'uri_is_prefix': True,
        },
        BASE_URI,
        DIR_URI),
))
def test_url_to_uri(args, kwargs, url, uri):
    u = URLToURI(*args, **kwargs)
    assert u.url == url
    assert u.uri == uri
    assert u.location == u.url


def test_no_rel_url(caplog):
    error = 'cannot be relative'
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            URLToURI('foo', 'about:blank')
    assert error in caplog.text


def test_url_must_be_prefix(caplog):
    error = "must have a path ending in '/'"
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            URLToURI(
                'about:blank',
                 str(BASE_URI),
                 strip_suffixes=[],
                 uri_is_prefix=True,
            )
    assert error in caplog.text


def test_uri_to_uri_str():
    u = URLToURI(str(FOO_YAML_URI), str(OTHER_URI))
    assert str(u) == f'(url: <{FOO_YAML_URI}>, uri: <{OTHER_URI}>)'
