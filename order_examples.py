import argparse
import json
import tempfile
from contextlib import closing, contextmanager
from dataclasses import asdict
from pathlib import Path

from archive.export import fetch_package
from catalog.lifecycle import retire_source
from catalog.schema import open_catalog
from handoff import initialize
from intake.register import register
from publish.commit import PublicationCommitError
from publish.window import publish_window
from review.read import read_package
from review.result import FurnaceReview, PointReading, ReviewResult, TrayReview
from review.validate import PackageValidationError
from tests.fixtures import publication_records


def balanced_submission():
    return {
        "batch_id": "order-shift", "revision": "device-export",
        "rows": [
            {"row_number": 101, "trays": [[{}, {}, {}]]},
            {"row_number": 108, "trays": [[{}], [], None]},
            {"row_number": 120, "trays": [None, [{}], []]},
            {"row_number": 137, "trays": [[{}, {}], [{}]]},
        ],
        "temperature": [[1, 41], [4, 7], [1, 0]],
        "pressure": [[3, 18], [1, 9], [4, 23]],
    }


def tie_submission():
    return {
        "batch_id": "order-tie", "revision": "device-export",
        "rows": [
            {"row_number": 10, "trays": [[{}, {}]]},
            {"row_number": 20, "trays": None},
            {"row_number": 30, "trays": [[{}]]},
            {"row_number": 44, "trays": [[{}]]},
            {"row_number": 70, "trays": [[{}, {}, {}, {}, {}]]},
        ],
        "temperature": [[3, 17]],
        "pressure": [[5, 19]],
    }


EXPECTED = ReviewResult((
    FurnaceReview(101, (TrayReview((PointReading(41, None), PointReading(None, None), PointReading(None, 18))),)),
    FurnaceReview(108, (TrayReview((PointReading(None, 9),)), TrayReview(()), None)),
    FurnaceReview(120, (None, TrayReview((PointReading(7, None),)), TrayReview(()))),
    FurnaceReview(137, (TrayReview((PointReading(0, None), PointReading(None, None))), TrayReview((PointReading(None, 23),)))),
))


def rejects(error, action, *args):
    try:
        action(*args)
    except error:
        return
    raise AssertionError(f"{action.__name__} should raise {error.__name__}")


@contextmanager
def publication_fault(db, table, *, after=1, at_commit=False):
    """Fault-inject an archive INSERT in a dedicated test catalog."""
    if type(after) is not int or after < 1:
        raise ValueError("after must be a positive insert count")
    target = "main.\"" + table.replace("\"", "\"\"") + "\""
    if at_commit:
        db.execute("""CREATE TABLE fixture_order_deferred (
            package_id INTEGER REFERENCES packages(package_id) DEFERRABLE INITIALLY DEFERRED
        )""")
        body = "INSERT INTO fixture_order_deferred VALUES (-1);"
        helper_table = "main.fixture_order_deferred"
    else:
        db.execute("CREATE TEMP TABLE fixture_order_counter (seen INTEGER)")
        db.execute("INSERT INTO fixture_order_counter VALUES (0)")
        body = f"""
            UPDATE fixture_order_counter SET seen = seen + 1;
            SELECT RAISE(ABORT, 'order fixture refused archive write')
            WHERE (SELECT seen FROM fixture_order_counter) >= {after};
        """
        helper_table = "temp.fixture_order_counter"
    try:
        db.execute(f"CREATE TEMP TRIGGER fixture_order_fault AFTER INSERT ON {target} BEGIN {body} END")
        try:
            yield
        finally:
            db.execute("DROP TRIGGER temp.fixture_order_fault")
    finally:
        db.execute(f"DROP TABLE {helper_table}")


def baseline():
    with closing(open_catalog(":memory:")) as db:
        db.execute("PRAGMA temp_store = MEMORY")
        initialize(db)
        revision = register(db, balanced_submission())
        ids = [publish_window(db, revision, lo, hi)[0]
               for lo, hi in ((0, 2), (2, 4), (0, 2), (2, 4))]
        a0, a1, b0, b1 = (fetch_package(db, key) for key in ids)
        assert len(set(ids)) == 4 and (a0, a1) == (b0, b1)
        before = publication_records(db)
        for at_commit in (False, True):
            with publication_fault(db, "publication_receipts", at_commit=at_commit):
                rejects(PublicationCommitError, publish_window, db, revision, 0, 2)
                assert not db.in_transaction and publication_records(db) == before
    assert ReviewResult(read_package(a0).rows + read_package(b1).rows) == EXPECTED
    print(json.dumps({"v1_package_ids": ids, "same_window_bytes": a1 == b1,
                      "offline_rows": [row.row_number for row in EXPECTED.rows]}))


def expect_plan(manifest, order_id, revision_id, start, stop, cuts, costs):
    plan = json.loads(manifest.decode("utf-8"))
    expected = {"order_id": order_id, "revision_id": revision_id, "start": start,
                "stop": stop, "cuts": cuts, "costs": costs}
    assert {key: plan[key] for key in expected} == expected
    return expected


def orders(*, verify):
    from archive.export import fetch_order
    from publish.window import publish_order
    from review.read import read_order

    with tempfile.TemporaryDirectory(prefix="furnace-order-") as work:
        path = Path(work) / "orders.sqlite3"
        with closing(open_catalog(path)) as db:
            initialize(db)
            raw = balanced_submission()
            revision = register(db, raw)
            a_id, manifest = publish_order(db, revision, 0, 4, [8, 8])
            b_id, _ = publish_order(db, revision, 0, 4, [8, 8])
            assert a_id != b_id
            plan = expect_plan(manifest, a_id, revision, 0, 4, [2], [6, 6])
            a = fetch_order(db, a_id)
            b = fetch_order(db, b_id)
            assert a[0] == manifest and len(a[1]) == len(b[1]) == 2
            if verify:
                tie = register(db, tie_submission())
                for caps, cuts, costs in (([6, 6, 6], [2, 4], [1, 4, 6]),
                                          ([6, 2, 6], [3, 4], [3, 2, 6])):
                    number, receipt = publish_order(db, tie, 1, 5, caps)
                    expect_plan(receipt, number, tie, 1, 5, cuts, costs)
                rejects(ValueError, publish_order, db, tie, 1, 5, [6, 6, 5])
            register(db, {**raw, "revision": "corrected", "temperature": [[1, 51], [4, 17], [1, 0]]})
            retire_source(db, revision)
        with closing(open_catalog(path)) as db:
            initialize(db)
            assert fetch_order(db, a_id) == a
            assert fetch_order(db, b_id) == b

    issued = a[1]
    result = read_order(manifest, issued[::-1])
    assert result == EXPECTED
    rejects(PackageValidationError, read_order, manifest, (issued[0], b[1][1]))
    if verify:
        rejects(PackageValidationError, read_order, manifest, issued[:1])
        rejects(PackageValidationError, read_order, manifest, (issued[0], issued[0]))
        rejects(PackageValidationError, read_order, manifest, (issued[0], b""))
    print(json.dumps({"plan": plan, "offline_review": asdict(result),
                      "mixed_order_rejected": True, "reopened_bytes_preserved": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Furnace order examples")
    parser.add_argument("mode", choices=("baseline", "verify", "demo"))
    mode = parser.parse_args().mode
    if mode == "baseline":
        baseline()
    else:
        orders(verify=mode == "verify")
