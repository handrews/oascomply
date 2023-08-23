from dataclasses import FrozenInstanceError
import pathlib
from typing import Tuple
from unittest.mock import MagicMock, patch

import pytest

from oascomply.oassource import (
    ParsedContent,
    ResourceLoader,
    FileLoader,
    HttpLoader,
    ContentParser,
    OASSource,
    MultiSuffixSource,
    FileMultiSuffixSource,
    HttpMultiSuffixSource,
    DirectMapSource,
)


def test_parsed_content():
    v = {'foo': 'bar'}
    url = 'about:blank'
    sourcemap = {}

    pc = ParsedContent(v, url, sourcemap)
    assert pc.value is v
    assert pc.url is url
    assert pc.sourcemap is sourcemap

    
    # Test frozen-ness
    with pytest.raises(FrozenInstanceError):
        pc.value = {}
    with pytest.raises(FrozenInstanceError):
        pc.url = 'https://example.com'
    with pytest.raises(FrozenInstanceError):
        pc.sourcemap = None
