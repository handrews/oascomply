import logging

import jschon

import pytest

from oascomply.cli import (
    ThingToURI,
    PathToURI,
    URLToURI,
    parse_logging,
    parse_non_logging,
    configure_manager,
)


logging.getLogger('oascomply').setLevel(logging.DEBUG)


BASE_URI = jschon.URI('https://example.com/')
FOO_YAML_URI = BASE_URI.copy(path='/foo.yaml')
FOO_URI = BASE_URI.copy(path='/foo')
OTHER_URI = jschon.URI('tag:example.com,2023:bar')

@pytest.mark.parametrize('args,thing,uri', (
    (['about:blank'], 'about:blank', jschon.URI('about:blank')),
    ([['about:blank']], 'about:blank', jschon.URI('about:blank')),
    ([str(FOO_YAML_URI), ['.json']], str(FOO_YAML_URI), FOO_YAML_URI),
    ([[str(FOO_YAML_URI)], ['.yaml']], str(FOO_YAML_URI), FOO_URI),
    ([str(BASE_URI), (), True], str(BASE_URI), BASE_URI),
    (
        [['foo', str(OTHER_URI)]],
        'foo',
        OTHER_URI,
    ),
    (
        [['foo.yaml', str(OTHER_URI)], ['.yaml']],
        'foo.yaml',
        OTHER_URI,
    ),
    (
        [['foo.yaml', str(FOO_YAML_URI)], ['.yaml']],
        'foo.yaml',
        FOO_YAML_URI,
    ),
    (
        [['foo', str(BASE_URI)], (), True],
        'foo',
        BASE_URI,
    ),
))
def test_thing_to_uri(args, thing, uri):
    t = ThingToURI(*args)
    assert t.thing == thing
    assert t.uri == uri


@pytest.mark.parametrize('args,error', (
    ([()], "Expected 1 or 2 values"),
    ([str(FOO_YAML_URI), (), True], "must have a path ending in '/'"),
    (['https://ex.org/?query', (), True], "not include a query or fragment"),
    (['https://ex.org/#frag', (), True], "not include a query or fragment"),
    (['foo'], 'cannot be relative'),
))
def test_thing_to_uri_errors(args, error, caplog):
    with caplog.at_level(logging.WARNING):
        with pytest.raises(ValueError, match=error):
            ThingToURI(*args)
    assert error in caplog.text


@pytest.mark.parametrize('args', (
    ['about:blank'],
    [[str(OTHER_URI), str(BASE_URI)], ['.json'], True],
))
def test_thing_to_uri_repr(args):
    t = ThingToURI(*args)
    repr_args = [
        [args[0]] if isinstance(args[0], str) else args[0],
        args[1] if len(args) > 1 else (),
        args[2] if len(args) > 2 else False,
    ]
    assert repr(t) == \
        f'ThingToURI({repr_args[0]}, {repr_args[1]}, {repr_args[2]})'
