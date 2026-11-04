#!/usr/bin/env python3
"""Safely create or reuse a private Debian 13 bearer-token file.

Never print the token on failure. A launcher may capture stdout directly into
an environment variable; operators should not run this helper in a terminal.
"""
from __future__ import annotations

import os
import secrets
import stat
import sys
from pathlib import Path


def read_or_create(path: Path) -> str:
    """Read an owner-only regular token file without following symlinks."""
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        pass
    except OSError:
        raise ValueError("Cannot securely create the private token file.") from None
    else:
        try:
            with os.fdopen(fd, "w", encoding="ascii") as stream:
                stream.write(secrets.token_urlsafe(48) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            raise ValueError("Cannot securely write the private token file.") from None

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "r", encoding="ascii") as stream:
            file_stat = os.fstat(stream.fileno())
            if (not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.geteuid()
                    or file_stat.st_nlink != 1
                    or stat.S_IMODE(file_stat.st_mode) & 0o077):
                raise ValueError("Token file must be owned by the user, regular and private (0600).")
            value = stream.read(1025).strip()
    except (OSError, UnicodeError):
        raise ValueError("Cannot securely read the private token file.") from None
    if (len(value) < 32 or len(value) > 1024 or not value.isascii()
            or any(not 33 <= ord(char) <= 126 for char in value)):
        raise ValueError("Token file contains an invalid private credential.")
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: private_token_file.py PATH (capture stdout; do not display)", file=sys.stderr)
        return 2
    try:
        value = read_or_create(Path(argv[1]))
    except ValueError as error:
        print("BLOCKED: " + str(error), file=sys.stderr)
        return 1
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
