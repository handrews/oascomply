import sys
import logging
from pathlib import Path

import jschon

import pytest

from oascomply.urimapping import LocationToURI, PathToURI, URLToURI
from oascomply.cli import (
    parse_logging, ActionAppendLocationToURI,
)
from oascomply.cli.oascomply import parse_non_logging

from . import (
    BASE_URI,
    FOO_YAML_URI,
    FOO_URI,
    DIR_URI,
    OTHER_URI,
    URN_URI,
    FOO_JSON_PATH,
    FOO_PATH,
    FOO_JSON_PATH_URL,
    FOO_PATH_URL,
    CURRENT_DIR,
    CURRENT_DIR_URL,
)


DEFAULT_ARG_NAMESPACE = {
    'initial': None,
    'files': [],
    'urls': [],
    'strip_suffixes': ('.json', '.yaml', '.yml', ''),
    'directories': [],
    'url_prefixes': [],
    'dir_suffixes': ('.json', '.yaml', '.yml'),
    'url_suffixes': (),
    'number_lines': False,
    'examples': 'true',
    'output_format': None,
    'output_file': None,
    'test_mode': False,
    'verbose': 0,
}


def _override_args(**kwargs):
    overridden = DEFAULT_ARG_NAMESPACE.copy()
    overridden.update(kwargs)
    return overridden


def test_action_wrong_nargs():
    with pytest.raises(ValueError, match=r'expected nargs="\+"'):
        ActionAppendLocationToURI(
            '-f',
            'foo',
            nargs='*',
            arg_cls=LocationToURI,
            strip_suffixes=(),
        )


@pytest.mark.parametrize('argv,level,remaining', (
    (['--file'], logging.WARNING, ['--file']),
    (['-v', '--v1', '--v2'], logging.INFO, ['--v1', '--v2']),
    (['-vv'], logging.DEBUG, []),
    (['-v', '-v'], logging.DEBUG, []),
))
def test_parse_logging(argv, level, remaining):
    try:
        logger = logging.getLogger('oascomply')
        old_level = logger.getEffectiveLevel()

        remaining_args = parse_logging(argv)

        assert logger.getEffectiveLevel() == level
        assert remaining_args == remaining

    finally:
        logger.setLevel(old_level)


@pytest.mark.parametrize('argv,namespace', (
    ([], DEFAULT_ARG_NAMESPACE),
    (['--output-format'], _override_args(output_format='nt11')),
    (
        ['-o', 'toml', '-O', 'foo.toml'],
        _override_args(
            output_format='toml',
            output_file='foo.toml',
        ),
    ),
    (
        ['--output-file', 'foo.nt'],
        _override_args(output_file='foo.nt'),
    ),
    (
        ['-f', 'foo.yaml'],
        _override_args(
            files=[
                PathToURI(
                    'foo.yaml',
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
            ],
        )
    ),
    (
        ['-f', 'bar.json', 'Schema'],
        _override_args(
            files=[
                PathToURI(
                    'bar.json',
                    oastype='Schema',
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
            ],
        )
    ),
    (
        ['--file', 'foo.yaml', str(FOO_YAML_URI)],
        _override_args(
            files=[
                PathToURI(
                    'foo.yaml',
                    str(FOO_YAML_URI),
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
            ],
        ),
    ),
    (
        ['--file', 'foo.yaml', str(FOO_YAML_URI), str(URN_URI), str(OTHER_URI)],
        _override_args(
            files=[
                PathToURI(
                    'foo.yaml',
                    str(FOO_YAML_URI),
                    additional_uris=(str(URN_URI), str(OTHER_URI)),
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
            ],
        ),
    ),
    (
        ['-f', 'foo.yaml', '--file', 'bar.json', '-x'],
        _override_args(
            files=[
                PathToURI('foo.yaml', strip_suffixes=[]),
                PathToURI('bar.json', strip_suffixes=[]),
            ],
        ),
    ),
    (
        ['-u', str(FOO_YAML_URI), '--url', str(FOO_JSON_PATH_URL)],
        _override_args(
            urls=[
                URLToURI(
                    str(FOO_YAML_URI),
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
                URLToURI(
                    str(FOO_JSON_PATH_URL),
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
            ],
        ),
    ),
    (
        ['--url', str(FOO_YAML_URI), str(OTHER_URI), str(URN_URI)],
        _override_args(
            urls=[
                URLToURI(
                    str(FOO_YAML_URI),
                    str(OTHER_URI),
                    additional_uris=[str(URN_URI)],
                    strip_suffixes=DEFAULT_ARG_NAMESPACE['strip_suffixes'],
                ),
            ],
        ),
    ),
    (
        ['--url', str(FOO_YAML_URI), '--strip-suffixes=.yml'],
        _override_args(
            urls=[
                URLToURI(str(FOO_YAML_URI), strip_suffixes=['.yml']),
            ],
        ),
    ),
    (
        [
            '-d', str(CURRENT_DIR / 'oascomply'),
            '--directory', str(CURRENT_DIR / 'tests'),
        ],
        _override_args(
            directories=[
                PathToURI(str(CURRENT_DIR / 'oascomply')),
                PathToURI(str(CURRENT_DIR / 'tests')),
            ],
        ),
    ),
    (
        ['-i', str(FOO_URI)],
        _override_args(initial=str(FOO_URI)),
    ),
    (
        ['--initial', str(OTHER_URI)],
        _override_args(initial=str(OTHER_URI)),
    ),
))
def test_parse_non_logging(argv, namespace):
    args = parse_non_logging(argv)
    for k, v in namespace.items():
        assert (getattr(args, k) == v), f'ARGUMENT: {k!r}'
