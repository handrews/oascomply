from __future__ import annotations

from typing import Generator, Iterable, Sequence, Tuple, Union, overload
from collections import namedtuple
import re
import jschon
import logging

from oascomply.resourceid import JsonPtr, RelJsonPtr

logger = logging.getLogger(__name__)


TEMPLATE_UNESCAPED = r'[\x00-.0-z|\x7f-\U0010ffff]'
TEMPLATE_VARIABLE = f'{TEMPLATE_UNESCAPED}*'
TEMPLATE_TOKEN = r'\{(' + TEMPLATE_VARIABLE + r')\}'
TEMPLATE_ESCAPED = r'\~[0123]'
NON_TEMPLATE_TOKEN = f'({TEMPLATE_UNESCAPED}|{TEMPLATE_ESCAPED})*'
BASIC_POINTER_TEMPLATE = f'(/({TEMPLATE_TOKEN}|{NON_TEMPLATE_TOKEN}))*'
JSON_POINTER_TEMPLATE = f'{BASIC_POINTER_TEMPLATE}({TEMPLATE_TOKEN}#)?'

PARENT_COUNT = '(0|([1-9][0-9]*))'
INDEX_MANIPULATION = r'((\+|-)[1-9][0-9]*)?'
RELATIVE_JSON_POINTER_TEMPLATE = (
    f'{PARENT_COUNT}{INDEX_MANIPULATION}(#|{JSON_POINTER_TEMPLATE})'
)


TemplateResult = namedtuple(
    'TemplateResult',
    ['pointer', 'data', 'variables', 'index'],
)


class GenericPtrTemplateError(Exception):
    pass


class JsonPtrTemplateError(GenericPtrTemplateError):
    pass


class InvalidJsonPtrTemplateError(JsonPtrTemplateError):
    pass


class JsonPtrTemplateEvaluationError(JsonPtrTemplateError):
    pass


class JsonPtrTemplate(Sequence[str]):
    """
    The inteface of this class is essentially a copy of jschon.JSONPointer.
    """
    def __new__(cls, *values: Union[str, Iterable[str]]) -> JsonPtrTemplate:
        self = object.__new__(cls)

        # TODO: New signature
        if (m := re.fullmatch(JSON_POINTER_TEMPLATE, template)) is None:
            raise InvalidJsonPtrTemplateError(
                f'{template!r} is not a valid JsonPtrTemplate!'
            )
        if len(values) == 1 and isin
        self._template = template

        # Splitting '' results in [''], and '/' in ['', ''],
        # so always remove the initial ''
        self._segments = template.split('/')[1:]

        # Components are one of:
        # * JsonPtr instances
        # * A template variable name (str instance)
        # * Boolean True to request the name of the key or number
        #   of the index matching the previous variable; this can
        #   only occur as the last component
        self._components= []
        currptr = JsonPtr()
        for s in self._segments:
            if s.startswith('{'):
                if len(currptr) > 0:
                    self._components.append(currptr)
                    currptr = JsonPtr()
                if s.endswith('#'):
                    self._components.extend((s[1:-2], True))
                else:
                    self._components.append(s[1:-1])
            else:
                currptr /= self.unescape(s)

        if len(currptr) or not len(self._components):
            self._components.append(currptr)

        return self

    def __str__(self):
        return self._template

    def __len__(self):
        return len(self._segments)

    @overload
    def __getitem__(self, index: int) -> str:
        ...

    @overload
    def __getitem__(self, index: slice) -> JsonPtrTemplate:
        ...

    def __getitem__(self, index):
        if isinstance(index, int):
            return self._segments[index]
        if isinstance(index, slice):
            return JsonPtrTemplate(self._segments[index])
        raise TypeError("Expecting int or slice")

    @overload
    def __truediv__(self, suffix: str) -> JsonPtrTemplate:
        ...

    @overload
    def __truediv__(self, suffix: Iterable[str]) -> JsonPtrTemplate:
        ...

    def __truediv__(self, suffix) -> JsonPtrTemplate:
        if isinstance(suffix, str):
            return JsonPtrTemplate(self, (suffix,))
        if isinstance(suffix, Iterable):
            return JsonPtrTemplate(self, suffix)
        return NotImplemented

    def __eq__(self, other: JsonPtrTemplate) -> bool:
        if isinstance(other, JsonPtrTemplate):
            return self._template == other._template
        return NotImplemented

    def __le__(self, other: JsonPtrTemplate) -> bool:
        """Return `self <= other` (self is a prefix of other)"""
        if isinstance(other, JsonPtrTemplate):
            return self._segments == other.segments[:len(self._segments)]
        return NotImplemented

    def __lt__(self, other: JsonPtrTemplate) -> bool:
        """Return `self < other` (other is a prefix of self)"""
        if isinstance(other, JsonPtrTemplate):
            return self._segments[:len(other._segments)] == other._segments
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._template)

    def evaluate(
        self,
        instance: jschon.JSON,
        *,
        require_match: bool = False,
        _index=0,
        _resolved=JsonPtr(),
        _variables=None,
        _previous_variable=None,
    ) -> Generator[
        Tuple[JsonPtr, jschon.JSON, Union[None, str, int]],
        None,
        None,
    ]:
        remaining = self._components[_index:]
        variables = _variables or {}

        if len(remaining) == 0:
            yield TemplateResult(_resolved, instance, variables, None)
            return

        next_c = remaining[0]
        if isinstance(next_c, JsonPtr):
            new_resolved = _resolved / next_c
            try:
                new_instance = next_c.evaluate(instance)
            except jschon.JSONPointerError as e:
                if not require_match:
                    return
                raise JsonPtrTemplateEvaluationError(
                    f"Path '{new_resolved}' not found in document {instance} while "
                    f"evaluating template '{self}'"
                ) from e

            yield from self.evaluate(
                new_instance,
                require_match=require_match,
                _index=_index + 1,
                _resolved=new_resolved,
                _variables=variables,
            )

        elif isinstance(next_c, str):
            if instance.type == 'array':
                keys = range(len(instance))
            elif instance.type == 'object':
                keys = instance.keys()
            else:
                raise JsonPtrTemplateEvaluationError(
                    f"Cannot match template variable {next_c!r} from "
                    f"template '{self}' – instance locattion '{_resolved}' "
                    f"is a {instance.type!r}, not an array or object."
                )

            for key in keys:
                newvars = variables.copy()
                newvars[next_c] = key
                yield from (
                    self.evaluate(
                        instance[key],
                        require_match=require_match,
                        _index=_index + 1,
                        _resolved=_resolved / str(key),
                        _variables=newvars,
                    )
                )
        else:
            assert next_c is True
            prev_val = next(reversed(variables.values()))
            yield TemplateResult(_resolved, instance, variables, prev_val)

    def matches(self, ptr: JsonPtr):
        if len(ptr) != len(self):
            logger.error('len mismatch')
            return False

        ptr_segments = [list(ptr)]
        logger.error(f'{self._segments} =? {ptr_segments}')
        variables = {}
        for i in range(len(ptr_segments)):
            if ptr_segments[i] != self._segments[i]:
                if self._segments[i].startswith('{'):
                    variables[self._segments[i][1:-1]] = ptr_segments[i]
                else:
                    logger.error(f'seg mismatch {ptr_segments[i]!r} != {self._segments[i]!r}')
                    return False
        return True


    @staticmethod
    def escape(component):
        return (
            component
                .replace('~', '~0')
                .replace('/', '~1')
                .replace('{', '~2')
                .replace('}', '~3')
        )

    @staticmethod
    def unescape(component):
        return (
            component
                .replace('~3', '}')
                .replace('~2', '{')
                .replace('~1', '/')
                .replace('~0', '~')
        )


class RelJsonPtrTemplateError(GenericPtrTemplateError):
    pass


class InvalidRelJsonPtrTemplateError(
    RelJsonPtrTemplateError
):
    pass


class RelJsonPtrTemplateEvaluationError(
    RelJsonPtrTemplateError
):
    pass


class RelJsonPtrTemplate:
    def __init__(self, template: str):
        try:
            try:
                slash = template.index('/')
                if template[slash -1] == '#':
                    raise InvalidRelJsonPtrTemplateError(
                        "Can't use '#' in origin adjustment with template path"
                    )
                self._relptr = RelJsonPtr(template[:slash])
                self._jptemplate = JsonPtrTemplate(template[slash:])
            except ValueError:
                self._relptr = RelJsonPtr(template)
                self._jptemplate = None
        except (
            jschon.JSONPointerError,
            jschon.RelativeJSONPointerError,
            InvalidJsonPtrTemplateError,
        ) as e:
            raise InvalidRelJsonPtrTemplateError(
                f"{template!r} is not a valid RelJsonPtrTemplate!",
            ) from e
        self._template = template

    def __str__(self):
        return self._template

    def __eq__(self, other):
        return (
            isinstance(other, type(self)) and
            self._template == other._template
        )

    def evaluate(self, instance, *, require_match=False):
        try:
            base = self._relptr.evaluate(instance)
        except jschon.RelativeJSONPointerError as e:
            raise RelJsonPtrTemplateEvaluationError(
                f"Could not evaluate origin adjustment of {self._template}",
            ) from e

        if self._jptemplate is None:
            if self._relptr.index:
                # Since we already evaluated the full relptr,
                # we know this will not raise an exception
                value = RelJsonPtr(
                    self._template[:-1]
                ).evaluate(instance)
                name = base
            else:
                value = base
                name = None
            yield TemplateResult(self._relptr, value, {}, name)
            return

        try:
            yield from (
                TemplateResult(
                    RelJsonPtr(
                        up=self._relptr.up,
                        over=self._relptr.over,
                        ref=result[0],
                    ),
                    result.data,
                    result.variables,
                    result.index,
                )
                for result in self._jptemplate.evaluate(
                    base,
                    require_match=require_match,
                )
            )
        except JsonPtrTemplateError as e:
            raise RelJsonPtrTemplateEvaluationError(
                e.args[0] +
                f" (after applying relative pointer '{self._relptr}')",
            ) from e
