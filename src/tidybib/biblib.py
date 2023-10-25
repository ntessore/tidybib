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
import warnings
from collections.abc import Mapping
from typing import Iterator, NamedTuple, NoReturn, TextIO, TypeAlias


## LOW-LEVEL API #######################################################


# Match sequences of legal identifier characters, except that the
# first is not allowed to be a digit (see id_class)
ID_RE = re.compile("(?![0-9])(?:(?![ \t\"#%'(),={}])[\x20-\x7f])+")

# BibTeX only considers space, tab, and newline to be white space (see
# lex_class)
SPACE_RE = re.compile("[ \t\n]*")


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


class BibtexComment(NamedTuple):
    """Container for BibTeX comment commands.

    This is always empty, since BibTeX does not parse comments.

    """


class BibtexPreamble(NamedTuple):
    """Container for BibTeX preamble commands."""

    preamble: str


class BibtexString(NamedTuple):
    """Container for BibTeX string commands."""

    name: str
    value: str


class BibtexEntry(NamedTuple):
    """Container for BibTeX entries."""

    entry_type: str
    key: str
    fields: dict[str, str | BibtexMacro]


#: Type alias for the possible content types in a BibTeX file.
BibtexContent: TypeAlias = BibtexComment | BibtexPreamble | BibtexString | BibtexEntry


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


class BibtexParser:
    """Parser instance for a BibTeX file."""

    def __init__(self, data: str, filename: str) -> None:
        # used for warnings
        self.filename = filename

        # Remove trailing whitespace from lines in data (see input_ln
        # in bibtex.web)
        self.data = re.sub("[ \t]+$", "", data, flags=re.MULTILINE)

        # these will be set in parse()
        self.off = 0
        self.good = 0
        self.macros: dict[str, str] = {}
        self.warn_macros = True

    @property
    def _eof(self) -> bool:
        """Return true if parser is at end of file."""
        return self.off == len(self.data)

    def _fail(self, msg: str, good: int | None = None) -> NoReturn:
        """Raise a BibTeX parsing error."""
        if good is None:
            good = self.good
        raise BibtexError(_msg_with_context(msg, self.data, good, self.off))

    def _warn(self, msg: str, good: int | None = None) -> None:
        """Emit a BibTeX parsing warning."""
        if good is None:
            good = self.good
        warnings.warn_explicit(
            _msg_with_context(msg, self.data, good, self.off),
            BibtexWarning,
            self.filename,
            -1,
        )

    def _skip_space(self) -> None:
        # This is equivalent to eat_bib_white_space, except that we do
        # it automatically after every token, whereas bibtex carefully
        # and explicitly does it between every token.
        if m := SPACE_RE.match(self.data, self.off):
            self.off = m.end()

    def _try_tok(
        self,
        regexp: re.Pattern[str] | str,
        skip_space: bool = True,
    ) -> str | None:
        """Scan regexp followed by white space.

        Returns the matched text, or None if the match failed."""
        if isinstance(regexp, str):
            regexp = re.compile(regexp)
        m = regexp.match(self.data, self.off)
        if m is None:
            return None
        self.off = m.end()
        if skip_space:
            self._skip_space()
        return m.group(0)

    def _scan_balanced_text(self, term: str) -> str:
        """Scan brace-balanced text terminated with character term."""
        start, level = self.off, 0
        while not self._eof:
            char = self.data[self.off]
            if level == 0 and char == term:
                text = self.data[start : self.off]
                self.off += 1
                self._skip_space()
                return text
            elif char == "{":
                level += 1
            elif char == "}":
                level -= 1
                if level < 0:
                    self._fail("unexpected }", start)
            self.off += 1
        self._fail("unterminated string", start)

    def _tok(
        self,
        regexp: re.Pattern[str] | str,
        fail: str,
    ) -> str:
        """Scan token regexp or fail with the given message."""
        result = self._try_tok(regexp)
        if result is None:
            self.off += 1
            self._fail(fail)
        return result

    def _scan_identifier(self, good: int | None = None) -> str:
        return self._tok(ID_RE, "expected identifier").lower()

    def _scan_command_or_entry(self) -> None | BibtexContent:
        # See get_bib_command_or_entry_and_process

        # Skip to the next database entry or command
        self._tok("[^@]*", "unexpected end of file")
        self.good = self.off
        if self._try_tok("@") is None:
            return None

        # Scan command or entry type
        typ = self._scan_identifier()

        if typ == "comment":
            # Believe it or not, BibTeX doesn't do anything with what
            # comes after an @comment, treating it like any other
            # inter-entry noise.
            return BibtexComment()

        left = self._tok("[{(]", "expected { or ( after entry type")
        right, right_re = (")", "\\)") if left == "(" else ("}", "}")

        if typ == "preamble":
            # Parse the preamble, and return it without key
            preamble = self._scan_field_value()
            self._tok(right_re, f"expected {right}")
            return BibtexPreamble(preamble)

        if typ == "string":
            # Parse the macro, store it, and return its value
            name = self._scan_identifier()
            self._tok("=", "expected = after string name")
            value = self._scan_field_value()
            self._tok(right_re, f"expected {right}")
            if name in self.macros:
                self._warn(f"string `{name}' redefined")
            self.macros[name] = value
            return BibtexString(name, value)

        # Not a command, must be a database entry

        # Scan the entry's database key
        if left == "(":
            # The database key is anything up to a comma, white
            # space, or end-of-line (yes, the key can be empty,
            # and it can include a close paren)
            key = self._tok("[^, \t\n]*", "missing key")
        else:
            # The database key is anything up to comma, white
            # space, right brace, or end-of-line
            key = self._tok("[^, \t}\n]*", "missing key")

        # Scan fields (starting with comma or close after key)
        fields: dict[str, str | BibtexMacro] = {}
        while True:
            if self._try_tok(right_re, skip_space=False) is not None:
                break
            self._tok(",", f"expected {right} or ,")
            if self._try_tok(right_re, skip_space=False) is not None:
                break

            if self._eof:
                self._fail("input ended prematurely")

            # Scan field name and value
            field_off = self.off
            field = self._scan_identifier()
            self._tok("=", "expected = after field name")
            value = self._scan_field_value()

            if field in fields:
                self._warn(f"repeated field `{field}' in entry `{key}'", field_off)
                continue

            fields[field] = value

        return BibtexEntry(typ, key, fields)

    def _scan_field_value(self) -> str | BibtexMacro:
        # See scan_and_store_the_field_value_and_eat_white
        value = self._scan_field_piece()
        while self._try_tok("#") is not None:
            value += self._scan_field_piece()
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
        return value

    def _scan_field_piece(self) -> str | BibtexMacro:
        # See scan_a_field_token_and_eat_white
        piece = self._try_tok("[0-9]+")
        if piece is not None:
            return piece
        if self._try_tok("{", skip_space=False) is not None:
            return self._scan_balanced_text("}")
        if self._try_tok('"', skip_space=False) is not None:
            return self._scan_balanced_text('"')
        piece = self._try_tok(ID_RE)
        if piece is not None:
            try:
                value = self.macros[piece.lower()]
            except KeyError:
                if self.warn_macros:
                    self._warn(f"unknown macro `{piece}'")
                value = ""
            return BibtexMacro(piece, value)
        self._fail("expected string, number, or macro name")

    def iterparse(
        self,
        macros: Mapping[str, str] = {},
        warn_macros: bool = True,
    ) -> Iterator[BibtexContent]:
        """Parse BibTeX."""

        # mutable macros dict that is updated with @string definitions
        self.macros = {**macros}
        self.warn_macros = warn_macros

        # reset state
        self.off = self.good = 0

        # get content until None is returned, which signals EOF
        content: Iterator[BibtexContent] = iter(self._scan_command_or_entry, None)
        yield from content


## HIGH-LEVEL API ######################################################

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
    "number",
    "eid",
    "pages",
    "doi",
    "archiveprefix",
    "eprint",
    "primaryclass",
    "adsurl",
    "adsnote",
]


def _order_fields(field: str) -> tuple[int, str]:
    """Return the order of field items."""
    try:
        return (ORDER.index(field), field)
    except ValueError:
        return (len(ORDER), field)


class BibtexFields(dict[str, str | BibtexMacro]):
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
            for field in sorted(self, key=_order_fields):
                value = self[field]
                field = PRETTY.get(field, field)
                if macro := getattr(value, "macro", None):
                    value = macro
                else:
                    if field == "title":
                        if value and value[0] == "{" and value[-1] == "}":
                            value = '"' + value + '"'
                        else:
                            value = '"{' + value + '}"'
                    elif field == "year" and value.isdigit():
                        pass
                    else:
                        value = "{" + value + "}"
                out += f",\n{field:>13} = {value}"
            out += "\n}"
        return out


class BibtexData(NamedTuple):
    """Container for BibTeX data: preamble, strings, and entries."""

    preamble: list[str]
    strings: dict[str, str]
    entries: dict[str, BibtexFields]


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
    try:
        filename = fp.name
    except AttributeError:
        filename = "<stream>"
    return loads(data, filename, macros=macros, warn_macros=warn_macros)


def loads(
    data: str,
    filename: str | None = None,
    /,
    *,
    macros: Mapping[str, str] = {},
    warn_macros: bool = True,
) -> BibtexData:
    """Parse BibTeX from a string."""

    # the contents of the BibTeX database
    preamble: list[str] = []
    strings: dict[str, str] = {}
    entries: dict[str, BibtexFields] = {}

    # create a parser
    if filename is None:
        filename = "<string>"
    parser = BibtexParser(data, filename)

    # parse entries
    for item in parser.iterparse(macros, warn_macros):
        if isinstance(item, BibtexComment):
            # nothing can be done
            pass
        elif isinstance(item, BibtexPreamble):
            preamble.append(item.preamble)
        elif isinstance(item, BibtexString):
            strings[item.name] = item.value
        else:
            if item.key in entries:
                parser._warn(f"repeated entry `{item.key}'")
            entries[item.key] = BibtexFields(item.entry_type, item.fields)

    return BibtexData(preamble, strings, entries)


def iterdump(bib: BibtexData, /) -> Iterator[str]:
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
