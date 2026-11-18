import sqlite3

from exchange.catalog import read_received_day
from publication.evidence import SealedDay
from publication.read import read_sealed_day


def read_review_day(db: sqlite3.Connection, result_id: str, *, archive: bool = False) -> SealedDay:
    if archive:
        return read_received_day(db, result_id).day
    return read_sealed_day(db, result_id)
