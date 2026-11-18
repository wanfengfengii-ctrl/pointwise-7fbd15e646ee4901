from archive.envelope import PackageEnvelope
from layout.codec import decode_positions
from layout.shape import iter_point_addresses
from review.result import FurnaceReview, PointReading, ReviewResult, TrayReview


def assemble_result(package: PackageEnvelope, slot_count: int) -> ReviewResult:
    """Assemble a validated package by its common logical point slots."""
    temperature = dict(decode_positions(package.temperature, slot_count))
    pressure = dict(decode_positions(package.pressure, slot_count))
    points_by_tray: dict[tuple[int, int], list[PointReading]] = {}
    for slot, (row_index, tray_index, _) in enumerate(iter_point_addresses(package.rows)):
        point = PointReading(temperature.get(slot), pressure.get(slot))
        points_by_tray.setdefault((row_index, tray_index), []).append(point)

    rows = []
    for row_index, row in enumerate(package.rows):
        if row.trays is None:
            rows.append(FurnaceReview(row.row_number, None))
            continue
        trays = []
        for tray_index, tray in enumerate(row.trays):
            if tray is None:
                trays.append(None)
            else:
                readings = points_by_tray.get((row_index, tray_index), ())
                trays.append(TrayReview(tuple(readings)))
        rows.append(FurnaceReview(row.row_number, tuple(trays)))
    return ReviewResult(tuple(rows))
