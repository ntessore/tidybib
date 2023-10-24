# biblib -- parser for BibTeX files, adapted for tidybib
#
# Copyright (c) 2023 Nicolas Tessore
# Copyright (c) 2013 Austin Clements
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
"""Parser for BibTeX files.

This parser is derived directly from the WEB source code for BibTeX --
especially section "Reading the database file(s)" -- and hence (barring
bugs in translation) should be fully compatible with BibTeX's own
parser.

"""

import re
from collections.abc import Mapping
from typing import Generator, NamedTuple, NoReturn, TextIO
from warnings import warn

# Match sequences of legal identifier characters, except that the
# first is not allowed to be a digit (see id_class)
ID_RE = re.compile("(?![0-9])(?:(?![ \t\"#%'(),={}])[\x20-\x7f])+")

# BibTeX only considers space, tab, and newline to be white space (see
# lex_class)
SPACE_RE = re.compile("[ \t\n]*")

# Pretty field names
PRETTY = {
    "archiveprefix": "archivePrefix",
    "primaryclass": "primaryClass",
}

# Default order of fields
ORDER = [
    "author",
    "title",
    "journal",
    "keywords",
    "year",
    "month",
    "volume",
    "pages",
    "doi",
    "archiveprefix",
    "eprint",
    "primaryclass",
    "adsurl",
    "adsnote",
]


class BibtexError(ValueError):
    """Exception raised for BibTeX parsing errors."""


class BibtexWarning(Warning):
    """Warning category for BibTex parsing."""


class BibtexMacro(str):
    """String class that encapsulates a BibTeX macro."""

    macro: str
    """BibTeX macro name."""

    def __new__(cls, macro: str, value: str) -> "BibtexMacro":
        self = super().__new__(cls, value)
        self.macro = macro
        return self


def _order_fields(field: str) -> tuple[int, str]:
    """Return the order of field items."""
    try:
        return (ORDER.index(field), field)
    except ValueError:
        return (len(ORDER), field)


class BibtexEntry(dict[str, str | BibtexMacro]):
    """Dictionary class with an *entry_type* attribute."""

    def __init__(
        self,
        entry_type: str,
        data: Mapping[str, str] | None = None,
        /,
        **fields: str,
    ) -> None:
        self.entry_type = entry_type
        args = () if data is None else (data,)
        super().__init__(*args, **fields)

    def __repr__(self) -> str:
        name = self.__class__.__name__
        data = super().__repr__()
        return f"{name}({self.entry_type!r}, {data})"

    def __str__(self) -> str:
        data = super().__repr__()
        return f"{self.entry_type!s}({data})"

    def __format__(self, key: str) -> str:
        """Format entry in standard form using *key*."""

        out = f"@{self.entry_type.upper()}{{{key}"
        if len(self) == 0:
            out += "}"
        else:
            out += ",\n"
            for field in sorted(self, key=_order_fields):
                value = self[field]
                field = PRETTY.get(field, field)
                if macro := getattr(value, "macro", None):
                    value = macro
                elif value.isdigit():
                    pass
                else:
                    if field == "title":
                        if value and value[0] == "{" and value[-1] == "}":
                            value = '"' + value + '"'
                        else:
                            value = '"{' + value + '}"'
                    else:
                        value = "{" + value + "}"
                out += f"{field:>13} = {value},\n"
            out += "}"
        return out


class BibtexData(NamedTuple):
    """Container for BibTeX data: preamble, strings, and entries."""

    preamble: list[str]
    strings: dict[str, str]
    entries: dict[str, BibtexEntry]


def _msg_with_context(
    msg: str,
    data: str,
    start: int | None,
    stop: int,
    context: int = 10,
) -> str:
    """Add parsing context to an error or warning message."""
    if start is None:
        start = stop
        while start > 0 and stop - start < context:
            start -= 1
            if data[start] == "\n":
                start += 1
                break
    if start == stop:
        while stop < len(data) and stop - start < context:
            stop += 1
            if data[stop : stop + 1] == "\n":
                break
    if stop > start:
        msg = f"{msg}: {data[start : stop]}"
    return msg


def _fail(data: str, off: int, msg: str, good: int | None = None) -> NoReturn:
    """Raise a BibTeX parsing error."""
    raise BibtexError(_msg_with_context(msg, data, good, off))


def _warn(data: str, off: int, msg: str, good: int | None = None) -> None:
    """Emit a BibTeX parsing warning."""
    warn(_msg_with_context(msg, data, good, off), BibtexWarning)


def _skip_space(data: str, off: int) -> int:
    # This is equivalent to eat_bib_white_space, except that we do
    # it automatically after every token, whereas bibtex carefully
    # and explicitly does it between every token.
    if m := SPACE_RE.match(data, off):
        return m.end()
    return off


def _try_tok(
    data: str,
    off: int,
    regexp: re.Pattern[str] | str,
    skip_space: bool = True,
) -> tuple[int, str] | None:
    """Scan regexp followed by white space.

    Returns the matched text, or None if the match failed."""
    if isinstance(regexp, str):
        regexp = re.compile(regexp)
    m = regexp.match(data, off)
    if m is None:
        return None
    off = m.end()
    if skip_space:
        off = _skip_space(data, off)
    return off, m.group(0)


def _scan_balanced_text(
    data: str,
    off: int,
    term: str,
) -> tuple[int, str]:
    """Scan brace-balanced text terminated with character term."""
    start, level = off, 0
    off = off + 0  # ensure this is a new object
    while off < len(data):
        char = data[off]
        if level == 0 and char == term:
            text = data[start:off]
            return _skip_space(data, off + 1), text
        elif char == "{":
            level += 1
        elif char == "}":
            level -= 1
            if level < 0:
                _fail(data, off, "unexpected }", start)
        off += 1
    _fail(data, off, "unterminated string", start)


def _tok(
    data: str,
    off: int,
    regexp: re.Pattern[str] | str,
    fail: str,
    good: int | None = None,
) -> tuple[int, str]:
    """Scan token regexp or fail with the given message."""
    result = _try_tok(data, off, regexp)
    if result is None:
        _fail(data, off + 1, fail, good)
    return result


def _scan_identifier(
    data: str,
    off: int,
    good: int | None = None,
) -> tuple[int, str]:
    if good is None:
        good = off
    off, ident = _tok(data, off, ID_RE, "expected identifier", good)
    return off, ident.lower()


def _scan_command_or_entry(
    data: str,
    off: int,
    macros: dict[str, str],
    warn_macros: bool,
) -> tuple[int, str | None, BibtexEntry]:
    # See get_bib_command_or_entry_and_process

    # Skip to the next database entry or command
    good, _ = _tok(data, off, "[^@]*", "unexpected end of file")
    if _try_tok(data, good, "@") is None:
        return off, None, BibtexEntry("")

    # Scan command or entry type
    off, typ = _scan_identifier(data, good + 1)

    if typ == "comment":
        # Believe it or not, BibTeX doesn't do anything with what
        # comes after an @comment, treating it like any other
        # inter-entry noise.
        return off, None, BibtexEntry(typ)

    off, left = _tok(data, off, "[{(]", "expected { or ( after entry type", good)
    right, right_re = (")", "\\)") if left == "(" else ("}", "}")

    if typ == "preamble":
        # Parse the preamble, and return it without key
        off, preamble = _scan_field_value(data, off, good, macros, warn_macros)
        off, _ = _tok(data, off, right_re, f"expected {right}", good)
        return off, None, BibtexEntry(typ, {"preamble": preamble})

    if typ == "string":
        # Parse the macro, store it, and return its value
        off, name = _scan_identifier(data, off, good)
        off, _ = _tok(data, off, "=", "expected = after string name", good)
        off, value = _scan_field_value(data, off, good, macros, warn_macros)
        off, _ = _tok(data, off, right_re, f"expected {right}", good)
        if name in macros:
            _warn(data, off, f"macro `{name}' redefined", good)
        macros[name] = value
        return off, None, BibtexEntry(typ, {name: value})

    # Not a command, must be a database entry

    # Scan the entry's database key
    if left == "(":
        # The database key is anything up to a comma, white
        # space, or end-of-line (yes, the key can be empty,
        # and it can include a close paren)
        off, key = _tok(data, off, "[^, \t\n]*", "missing key")
    else:
        # The database key is anything up to comma, white
        # space, right brace, or end-of-line
        off, key = _tok(data, off, "[^, \t}\n]*", "missing key")

    # Scan fields (starting with comma or close after key)
    fields = BibtexEntry(typ)
    while True:
        if (result := _try_tok(data, off, right_re)) is not None:
            off, _ = result
            break
        off, _ = _tok(data, off, ",", f"expected {right} or ,", good)
        if (result := _try_tok(data, off, right_re)) is not None:
            off, _ = result
            break

        if off == len(data):
            _fail(data, off, "input ended prematurely", good)

        # Scan field name and value
        _off = off
        off, field = _scan_identifier(data, off, good)
        off, _ = _tok(data, off, "=", "expected = after field name", good)
        off, value = _scan_field_value(data, off, good, macros, warn_macros)

        if field in fields:
            _warn(data, off, f"repeated field `{field}' in entry `{key}'", _off)
            continue

        fields[field] = value

    return off, key, fields


def _scan_field_value(
    data: str,
    off: int,
    good: int,
    macros: Mapping[str, str],
    warn_macros: bool,
) -> tuple[int, str | BibtexMacro]:
    # See scan_and_store_the_field_value_and_eat_white
    off, value = _scan_field_piece(data, off, good, macros, warn_macros)
    while (result := _try_tok(data, off, "#")) is not None:
        off, _ = result
        off, _value = _scan_field_piece(data, off, good, macros, warn_macros)
        value += _value
    # Store if value is a macro, so that it can become one again below
    macro: str | None = getattr(value, "macro", None)
    # Compress spaces in the text.  Bibtex does this
    # (painstakingly) as it goes, but the final effect is the same
    # (see check_for_and_compress_bib_white_space).
    value = re.sub("[ \t\n]+", " ", value)
    # Strip leading and trailing space (literally just space, see
    # @<Store the field value string@>)
    value = value.strip(" ")
    # Turn value back into a macro if necessary
    if macro is not None:
        value = BibtexMacro(macro, value)
    return off, value


def _scan_field_piece(
    data: str,
    off: int,
    good: int,
    macros: Mapping[str, str],
    warn_macros: bool,
) -> tuple[int, str | BibtexMacro]:
    # See scan_a_field_token_and_eat_white
    piece = _try_tok(data, off, "[0-9]+")
    if piece is not None:
        return piece
    if (result := _try_tok(data, off, "{", skip_space=False)) is not None:
        off, _ = result
        return _scan_balanced_text(data, off, "}")
    if (result := _try_tok(data, off, '"', skip_space=False)) is not None:
        off, _ = result
        return _scan_balanced_text(data, off, '"')
    piece = _try_tok(data, off, ID_RE)
    if piece is not None:
        _off, macro = piece
        try:
            value = macros[macro.lower()]
        except KeyError:
            if warn_macros:
                _warn(data, _off, f"unknown macro `{macro}'", good)
            value = ""
        return _off, BibtexMacro(macro, value)
    _fail(data, off + 1, "expected string, number, or macro name", good)


def load(
    fp: TextIO,
    /,
    *,
    macros: Mapping[str, str] = {},
    warn_macros: bool = True,
) -> BibtexData:
    """Parse BibTeX from a text file object.

    The *macros* parameter can be used to provide expansions of *BibTeX*
    macros.  Substitutions are carried out while the input is parsed,
    and the expanded text is stored as a *BibtexMacro* instance, which
    is a *str* subclass that keeps track of the macro name.  Undefined
    macros in the BibTeX source emit a warning, unless *warn_macros* is
    set to false.

    """

    data = fp.read()
    return loads(data, macros=macros, warn_macros=warn_macros)


def loads(
    data: str,
    /,
    *,
    macros: Mapping[str, str] = {},
    warn_macros: bool = True,
) -> BibtexData:
    """Parse BibTeX from a string."""

    # mutable macros dict that is updated with @string definitions
    _macros: dict[str, str] = {**macros}

    # the contents of the BibTeX database
    preamble: list[str] = []
    strings: dict[str, str] = {}
    entries: dict[str, BibtexEntry] = {}

    # Remove trailing whitespace from lines in data (see input_ln
    # in bibtex.web)
    data = re.sub("[ \t]+$", "", data, flags=re.MULTILINE)

    # Parse entries
    off = 0
    while off < len(data):
        good = off
        off, entry, fields = _scan_command_or_entry(data, off, _macros, warn_macros)
        if entry is None:
            if fields.entry_type == "":
                break
            elif fields.entry_type == "preamble":
                preamble.append(fields["preamble"])
            elif fields.entry_type == "string":
                strings.update(fields)
            else:
                raise ValueError(f"unknown entry type: {fields.entry_type}")
        else:
            if entry in entries:
                _warn(data, off, f"repeated entry `{entry}'", good)
            if fields is not None:
                entries[entry] = fields

    return BibtexData(preamble, strings, entries)


def iterdump(bib: BibtexData, /) -> Generator[str, None, None]:
    """Yield formatted lines of BibTeX data."""

    if bib.preamble:
        for line in bib.preamble:
            yield f'@PREAMBLE{{"{line}"}}'
        yield ""

    if bib.strings:
        for macro, value in bib.strings.items():
            yield f'@STRING{{{macro} = "{value}"}}'
        yield ""

    for key, entry in bib.entries.items():
        yield format(entry, key)
        yield ""


def dump(fp: TextIO, bib: BibtexData, /) -> None:
    """Write formatted BibTeX data to a text file object."""

    for line in iterdump(bib):
        fp.write(line + "\n")


def dumps(bib: BibtexData, /) -> str:
    """Format BibTeX data as a string."""

    return "\n".join(iterdump(bib))
