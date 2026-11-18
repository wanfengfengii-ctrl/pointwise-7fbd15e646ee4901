from archive.envelope import PackageEnvelope
from layout.validate import ObservationValidationError, validate_columns, validate_shape


class PackageValidationError(ValueError):
    pass


def validate_package(package: PackageEnvelope) -> int:
    try:
        slot_count = validate_shape(package.rows)
        validate_columns(package.temperature, package.pressure, slot_count)
    except ObservationValidationError as exc:
        raise PackageValidationError(str(exc)) from exc
    return slot_count
