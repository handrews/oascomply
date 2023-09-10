import argparse
from typing import Optional, Sequence, Type
import logging
import sys

from oascomply.urimapping import LocationToURI

__all__ = [
    'DEFAULT_SUFFIXES',
    'add_verbose_option',
    'add_strip_suffixes_option',
    'LocationToURIArgumentParser',
    'ActionAppendLocationToURI',
    'parse_logging',
]


logger = logging.getLogger(__name__)


DEFAULT_SUFFIXES = ('.json', '.yaml', '.yml', '')  # TODO: not sure about ''
"""Default suffixes stripped from -f paths and -u URLs"""


def add_verbose_option(parser):
    parser.add_argument(
        '-v',
        '--verbose',
        action='count',
        default=0,
        help="Increase verbosity; can passed twice for full debug output.",
    )


def add_strip_suffixes_option(parser):
    parser.add_argument(
        '-x',
        '--strip-suffixes',
        nargs='*',
        default=DEFAULT_SUFFIXES,
        help="For documents loaded with -f or -u without an explict URI "
            "assigned on the command line, assign a URI by stripping any "
            "of the given suffixes from the document's URL; passing this "
            "option without any suffixes disables this behavior, treating "
            "the unmodified URL as the URI; the default stripped suffixes "
            "are .json, .yaml, .yml",
    )


class LocationToURIArgumentParser(argparse.ArgumentParser):
    def _fix_message(self, message):
        # nargs=+ does not support metavar=tuple
        return message.replace(
            'FILES [FILES ...]',
            'FILE [URI] [URI ...] [TYPE]',
        ).replace(
            'DIRECTORIES [DIRECTORIES ...]',
            'DIRECTORY [URI_PREFIX]',
        ).replace(
            'URLS [URLS ...]',
            'URL [URI] [URI ...] [TYPE]',
        ).replace(
            'PREFIXES [PREFIXES ...]',
            'URL_PREFIX [URI_PREFIX]',
        )

    def format_usage(self):
        return self._fix_message(super().format_usage())

    def format_help(self):
        return self._fix_message(super().format_help())


class ActionAppendLocationToURI(argparse.Action):
    @classmethod
    def make_action(
        cls,
        arg_cls: Type[LocationToURI] = LocationToURI,
        strip_suffixes: Sequence[str] = (),
    ):
        logger.debug(f'Registering {arg_cls.__name__} argument action')
        return lambda *args, **kwargs: cls(
            *args,
            arg_cls=arg_cls,
            strip_suffixes=strip_suffixes,
            **kwargs,
        )

    def __init__(
        self,
        option_strings: str,
        dest: str,
        *,
        nargs: Optional[str] = None,
        arg_cls: Type[LocationToURI],
        strip_suffixes: Sequence[str],
        **kwargs
    ) -> None:
        if nargs != '+':
            raise ValueError(
                f'{type(self).__name__}: expected nargs="+"'
            )
        self._arg_cls = arg_cls
        self._strip_suffixes = strip_suffixes
        super().__init__(option_strings, dest, nargs=nargs, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        # This should do initial classification into locations, URIs,
        # and OASTypes.
        #
        # The first value is always a location (path or URL), the last
        # MAY be an OASType, and all others are URI (not URI-references).
        # URIs always have at least one ":" in them, and OASTypes never
        # include a ":", so this is a fast way to distinguish them.
        logger.debug(f'Examining {values!r} for {self._arg_cls.__name__}')

        location = values[0]
        oastype = None
        primary_uri = None
        additional_uris = []
        if len(values) > 1:
            if ':' not in values[-1]:
                oastype = values[-1]
                uris = values[1:-1]
            else:
                uris = values[1:]

            if uris:
                primary_uri = uris[0]
                additional_uris = uris[1:]

        arg_list = getattr(namespace, self.dest)
        arg_list.append(
            self._arg_cls(
                location,
                primary_uri,
                additional_uris=additional_uris,
                strip_suffixes=self._strip_suffixes,
                oastype=oastype,
            ),
        )


def parse_logging(args) -> Sequence[str]:
    """
    Parse logging options and configure logging before parsing everything else.

    Without doing this first, we lose valuable logging from the custom arg
    handling classes.  Note that the options are re-added to the main parsing
    pass so that they appear in the help output.
    """
    verbosity_parser = argparse.ArgumentParser(add_help=False)
    add_verbose_option(verbosity_parser)
    v_args, remaining_args = verbosity_parser.parse_known_args(args)

    oascomply_logger = logging.getLogger('oascomply')
    if v_args.verbose:
        if v_args.verbose == 1:
            oascomply_logger.setLevel(logging.INFO)
        else:
            oascomply_logger.setLevel(logging.DEBUG)
    else:
        oascomply_logger.setLevel(logging.WARNING)
    return remaining_args
