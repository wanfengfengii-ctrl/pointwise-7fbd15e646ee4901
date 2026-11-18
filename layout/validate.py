from layout.codec import decode_positions
from layout.shape import FurnaceRow, TrayShape, row_slot_count
from layout.stripe import Stripe, StripeError


class ObservationValidationError(ValueError):
    pass


def validate_shape(rows: tuple[FurnaceRow, ...]) -> int:
    previous = -1
    total = 0
    for row in rows:
        if not isinstance(row, FurnaceRow):
            raise ObservationValidationError('shape must contain furnace rows')
        if type(row.row_number) is not int or row.row_number <= previous:
            raise ObservationValidationError('row numbers must be nonnegative and strictly increasing')
        previous = row.row_number
        if row.trays is not None:
            if not isinstance(row.trays, tuple):
                raise ObservationValidationError(f'row {row.row_number} has an invalid tray sequence')
            for tray in row.trays:
                if tray is None:
                    continue
                if not isinstance(tray, TrayShape):
                    raise ObservationValidationError(f'row {row.row_number} has an invalid tray')
                if type(tray.point_count) is not int or tray.point_count < 0:
                    raise ObservationValidationError(f'row {row.row_number} has an invalid point count')
        total += row_slot_count(row)
    return total


def validate_columns(temperature: Stripe, pressure: Stripe, slot_count: int) -> None:
    for name, stripe in (('temperature', temperature), ('pressure', pressure)):
        try:
            decode_positions(stripe, slot_count)
        except StripeError as exc:
            raise ObservationValidationError(f'{name}: {exc}') from exc
