import sqlite3

from publication.read import read_sealed_day

from .package import make_package


def export_day(db: sqlite3.Connection, result_id: str) -> bytes:
    return make_package(read_sealed_day(db, result_id))
