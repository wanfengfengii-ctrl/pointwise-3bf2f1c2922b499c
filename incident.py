import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from corrections import CorrectionTransaction, RowChange, register_sheet
from exchange import export_day, import_day, initialize_archive
from publication import initialize_source, seal_day
from review import audit_after
from snapshots import LedgerError, freeze_table


def transaction(name, *changes):
    return CorrectionTransaction(name, tuple(RowChange(*change) for change in changes))


def check_seal():
    expected = {"status": "DAY_REPLAY_MISMATCH", "sealed_days": 0, "successful_receipts": 0}
    with closing(sqlite3.connect(":memory:")) as source:
        initialize_source(source, "incident-seal")
        first = freeze_table(source, "d1", "opening", {"x": 0})
        last = freeze_table(source, "d1", "closing", {"x": 2})
        register_sheet(source, "d1", "north", "north original", (transaction("A", ("x", 0, 1)),))
        register_sheet(source, "d1", "south", "south original", (transaction("D", ("x", 0, 2)),))
        try:
            receipt = seal_day(source, first, last, ("A", "D"))
        except LedgerError as exc:
            if exc.code != "DAY_REPLAY_MISMATCH":
                raise
            actual = {"status": exc.code}
        else:
            actual = {"status": "SEALED", "result_id": receipt.result_id}
        actual["sealed_days"] = source.execute("SELECT COUNT(*) FROM sealed_days").fetchone()[0]
        actual["successful_receipts"] = source.execute("SELECT COUNT(*) FROM successful_receipts").fetchone()[0]
    return expected, actual


def check_review():
    joint = [(0, 0, 0), (0, 0, 1), (1, 1, 1), (2, 2, 1)]
    repeated = [(0, 0, 0), (1, 0, 1), (1, 1, 1), (1, 2, 1)]
    expected = {"online": joint, "offline": joint, "repeated": repeated}
    keys = ("x", "y", "w")
    with TemporaryDirectory() as folder:
        archive_path = Path(folder) / "archive.sqlite3"
        with closing(sqlite3.connect(":memory:")) as source:
            initialize_source(source, "incident-review")
            first = freeze_table(source, "d1", "opening", {"x": 0, "y": 0, "w": 0, "z": 0})
            last = freeze_table(source, "d1", "closing", {"x": 2, "y": 2, "w": 1, "z": 1})
            register_sheet(source, "d1", "north", "north original", (
                transaction("D", ("x", 0, 2), ("y", 0, 2)),
                transaction("A", ("x", 0, 1), ("y", 0, 1), ("w", 0, 1)),
            ))
            register_sheet(source, "d1", "south", "south original", (
                transaction("M", ("z", 0, 1)),
                transaction("B", ("x", 1, 0), ("y", 1, 0)),
            ))
            receipt = seal_day(source, first, last, ("D", "M", "B", "A"))
            result_id = receipt.result_id
            online = audit_after(source, result_id, "M", keys)
            blob = export_day(source, result_id)
            with closing(sqlite3.connect(archive_path)) as archive:
                initialize_archive(archive)
                import_day(archive, blob)
            freeze_table(source, "d1", "later revision", {"x": 9, "y": 9, "w": 9, "z": 1})
        with closing(sqlite3.connect(archive_path)) as archive:
            offline = audit_after(archive, result_id, "M", keys, archive=True)
            offline_repeated = audit_after(archive, result_id, "M", ("w", "x", "w"), archive=True)
    return expected, {"online": online, "offline": offline, "repeated": offline_repeated}


def main():
    parser = argparse.ArgumentParser(description="Compare the day publication and handoff with the desk check.")
    parser.add_argument("case", nargs="?", choices=("all", "seal", "review"), default="all")
    requested = parser.parse_args().case
    checks = {"seal": check_seal, "review": check_review}
    failures = []
    for name, check in checks.items():
        if requested not in ("all", name):
            continue
        expected, actual = check()
        print(json.dumps({"case": name, "expected": expected, "actual": actual}, ensure_ascii=False))
        if actual != expected:
            failures.append(name)
    if failures:
        print("DAY_LEDGER_INCIDENT " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
