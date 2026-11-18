from collections.abc import Iterator
from dataclasses import dataclass


class ShapeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TrayShape:
    point_count: int


@dataclass(frozen=True, slots=True)
class FurnaceRow:
    row_number: int
    trays: tuple[TrayShape | None, ...] | None


def _parse_tray(raw: object) -> TrayShape | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ShapeError('a tray must be a point list or null')
    for point in raw:
        if not isinstance(point, dict) or point:
            raise ShapeError('a point must be represented by an empty object')
    return TrayShape(len(raw))


def parse_shape(raw: object) -> tuple[FurnaceRow, ...]:
    if not isinstance(raw, list):
        raise ShapeError('rows must be a list')
    rows = []
    for item in raw:
        if not isinstance(item, dict) or item.keys() != {'row_number', 'trays'}:
            raise ShapeError('each row needs row_number and trays')
        row_number = item['row_number']
        if type(row_number) is not int:
            raise ShapeError('row_number must be an integer')
        trays = item['trays']
        if trays is None:
            rows.append(FurnaceRow(row_number, None))
        elif isinstance(trays, list):
            rows.append(FurnaceRow(row_number, tuple(map(_parse_tray, trays))))
        else:
            raise ShapeError('trays must be a list or null')
    return tuple(rows)


def shape_to_wire(rows: tuple[FurnaceRow, ...]) -> list[dict]:
    wire_rows = []
    for row in rows:
        trays = None
        if row.trays is not None:
            trays = [
                None if tray is None else [{} for _ in range(tray.point_count)]
                for tray in row.trays
            ]
        wire_rows.append({'row_number': row.row_number, 'trays': trays})
    return wire_rows


def row_slot_count(row: FurnaceRow) -> int:
    if row.trays is None:
        return 0
    return sum(tray.point_count for tray in row.trays if tray is not None)


def iter_point_addresses(
    rows: tuple[FurnaceRow, ...],
) -> Iterator[tuple[int, int, int]]:
    """Yield positional row, tray and point indexes in logical slot order."""
    for row_index, row in enumerate(rows):
        if row.trays is None:
            continue
        for tray_index, tray in enumerate(row.trays):
            if tray is not None:
                for point_index in range(tray.point_count):
                    yield row_index, tray_index, point_index
