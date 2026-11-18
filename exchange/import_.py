import sqlite3

from .catalog import ReceivedCopy, register_copy
from .package import parse_package


def import_day(db: sqlite3.Connection, blob: bytes) -> ReceivedCopy:
    package = parse_package(blob)
    return register_copy(db, package)
