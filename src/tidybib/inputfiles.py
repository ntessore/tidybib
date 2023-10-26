"""Like fileinput, but for files, not lines."""

import io
import os
import sys
from typing import BinaryIO, Iterable, Iterator, Literal, Protocol, TextIO


class OpenHook(Protocol):
    def __call__(
        self,
        file: str,
        mode: Literal["r", "rb"] = "r",
        *,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> TextIO | BinaryIO:
        ...


def files(
    files: str | os.PathLike[str] | Iterable[str] | None = None,
    inplace: bool = False,
    backup: str | None = None,
    *,
    mode: Literal["r", "rb"] = "r",
    openhook: OpenHook | None = None,
    encoding: str | None = None,
    errors: str | None = None,
) -> Iterator[BinaryIO | TextIO]:
    """Return a fileinput.input()-like iterator over input files."""

    _files: tuple[str, ...]
    if isinstance(files, str):
        _files = (files,)
    elif isinstance(files, os.PathLike):
        _files = (os.fspath(files),)
    else:
        if files is None:
            files = sys.argv[1:]
        if not files:
            _files = ("-",)
        else:
            _files = tuple(files)

    backupsuffix: str = backup or ".bak"

    if mode not in ("r", "rb"):
        raise ValueError("InputFiles opening mode must be 'r' or 'rb'")
    write_mode = mode.replace("r", "w")
    isbinary = "b" in mode

    if openhook:
        if inplace:
            raise ValueError("cannot use openhook with inplace")
        if not callable(openhook):
            raise ValueError("openhook must be callable")

    if encoding:
        if isbinary:
            raise ValueError("cannot use encoding in binary mode")
    else:
        encoding = io.text_encoding(encoding)  # type: ignore

    for filename in _files:
        isstdin = False
        file: TextIO | BinaryIO
        backupfilename: str | None = None
        output: TextIO | BinaryIO | None = None
        stdout: TextIO | BinaryIO | None = None

        if filename == "-":
            isstdin = True
            file = sys.stdin
            if isbinary:
                try:
                    file = sys.stdin.buffer
                except AttributeError:
                    pass
        else:
            if inplace:
                backupfilename = os.fspath(filename) + backupsuffix
                try:
                    os.unlink(backupfilename)
                except OSError:
                    pass
                os.rename(filename, backupfilename)
                file = open(
                    backupfilename,
                    mode,
                    encoding=encoding,
                    errors=errors,
                )  # type: ignore
                try:
                    perm = os.fstat(file.fileno()).st_mode
                except OSError:
                    output = open(
                        filename,
                        write_mode,
                        encoding=encoding,
                        errors=errors,
                    )  # type: ignore
                else:
                    _mode = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
                    if hasattr(os, "O_BINARY"):
                        _mode |= os.O_BINARY
                    fd = os.open(filename, _mode, perm)
                    output = open(
                        fd,
                        write_mode,
                        encoding=encoding,
                        errors=errors,
                    )  # type: ignore
                    try:
                        os.chmod(filename, perm)
                    except OSError:
                        pass
                stdout = sys.stdout
                sys.stdout = output  # type: ignore
            else:
                if openhook:
                    file = openhook(
                        filename,
                        mode,
                        encoding=encoding,
                        errors=errors,
                    )
                else:
                    file = open(
                        filename,
                        mode,
                        encoding=encoding,
                        errors=errors,
                    )  # type: ignore

        recover = True
        try:
            yield file
            recover = False
        finally:
            if stdout is not None:
                sys.stdout = stdout  # type: ignore
            try:
                if output is not None:
                    output.close()
            finally:
                try:
                    if file and not isstdin:
                        file.close()
                finally:
                    if backupfilename is not None:
                        if recover:
                            os.rename(backupfilename, filename)
                        elif not backup:
                            try:
                                os.unlink(backupfilename)
                            except OSError:
                                pass
