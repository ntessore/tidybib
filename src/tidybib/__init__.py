import argparse
import filecmp
import os
import sys
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TextIO
from . import biblib

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
def _input(file: str) -> Iterator[TextIO]:
    """Opens an input file with '-' support."""
    if file == "-":
        yield sys.stdin
    else:
        with open(file) as fp:
            yield fp


@contextmanager
def _output(file: str, perm: int | None = None) -> Iterator[TextIO]:
    """Opens an output file with '-' support."""
    if file == "-":
        yield sys.stdout
    elif perm is None:
        with open(file, "w") as fp:
            yield fp
    else:
        fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, perm)
        with open(fd, "w") as fp:
            try:
                os.chmod(file, perm)
            except OSError:
                pass
            yield fp


def _tmpname(file: str) -> str:
    """Return the temporary file name for tidybib output."""
    if file == "-":
        return "-"
    prefix, name = os.path.split(file)
    return os.path.join(prefix, "." + name.lstrip(".") + ".tidy")


def _bakname(file: str) -> str:
    """Return the backup file name for tidybib input."""
    if file == "-":
        return ""
    return file + ".untidy"


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
        print("[WARNING]", f"{filename}:", message, file=file)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        warnings.simplefilter("always", biblib.BibtexWarning)
        warnings.showwarning = showwarning
        yield


@handle_warnings()
def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tidybib",
        description="BibTeX formatter",
        epilog="Report any issues to https://github.com/ntessore/tidybib",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="print output to stdout, do not modify files",
    )
    parser.add_argument(
        "bibfile",
        default="-",
        nargs="*",
        help="BibTeX source file(s)",
    )

    args = parser.parse_args()

    for file in args.bibfile:
        # parse BibTeX from the input file; dash "-" for stdin is supported
        with _input(file) as fp:
            bib = biblib.load(fp, macros=MACROS, warn_macros=False)

            # try and store file permissions for later
            perm = None
            if fp is not sys.stdin:
                try:
                    perm = os.fstat(fp.fileno()).st_mode
                except OSError:
                    pass

        # sort entries by year
        bib = bib._replace(
            entries=dict(sorted(bib.entries.items(), key=sortkey_year, reverse=True))
        )

        # get temporary output filename for the formatted file
        if args.stdout:
            out = "-"
        else:
            out = _tmpname(file)

        # write the reformatted BibTeX file to temporary file
        with _output(out, perm) as fp:
            biblib.dump(fp, bib)

        # if writing to stdout, we are done
        if out == "-":
            continue

        # compare input and output files -- only replace input if files differ
        if filecmp.cmp(file, out, shallow=False):
            # files are equal, remove temporary output
            os.unlink(out)
        else:
            # files not equal, get backup file name for original input file
            bak = _bakname(file)
            try:
                os.unlink(bak)
            except OSError:
                pass

            # try and move temporary file to input file
            cleanup = False
            try:
                os.rename(file, bak)
                cleanup = True
                os.rename(out, file)
                cleanup = False
            finally:
                if cleanup:
                    os.rename(bak, file)

    # all done
    return 0


if __name__ == "__main__":
    main()
