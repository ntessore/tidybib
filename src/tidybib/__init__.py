import sys
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO
from . import biblib, inputfiles

# default macros:
# - turn month names into numeric values
MACROS = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}

# character map for sorting same-date items by key in ascending order
REVERSE = str.maketrans(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "zyxwvutsrqponmlkjihgfedcbaZYXWVUTSRQPONMLKJIHGFEDCBA9876543210",
)


def sortkey_year(item: tuple[str, biblib.BibtexFields]) -> tuple[str, ...]:
    """Sort bibliography entries by year, month, key."""
    key, entry = item
    return (
        entry.get("year", "0"),  # sort by year in descending order
        entry.get("month", "0"),  # then by month in descending order
        key.translate(REVERSE),  # then by key in ascending order
    )


@contextmanager
def handle_warnings() -> Iterator[None]:
    """Custom handler for warnings."""

    def showwarning(
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: TextIO | None = None,
        line: str | None = None,
    ) -> None:
        parts = ["[WARNING]"]
        if filename and filename[0] + filename[-1] != "<>":
            parts += [f"{filename}:"]
        parts += [str(message)]
        print(*parts, file=file or sys.stderr)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        warnings.simplefilter("always", biblib.BibtexWarning)
        warnings.showwarning = showwarning
        yield


@handle_warnings()
def main() -> int:
    # iterate all input files or stdin
    for file in inputfiles.files(None, True, ".untidy"):
        # load current BibTeX file from string
        bib = biblib.load(file, macros=MACROS, warn_macros=False)

        # sort entries by year in reverse order
        entries = dict(sorted(bib.entries.items(), key=sortkey_year, reverse=True))

        # repack the bib tuple with the sorted entries
        bib = bib._replace(entries=entries)

        # output BibTeX in standard form to stdout, which points to file
        biblib.dump(sys.stdout, bib)

    # all done
    return 0


if __name__ == "__main__":
    main()
