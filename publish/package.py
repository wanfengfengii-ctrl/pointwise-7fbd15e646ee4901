from archive.envelope import EnvelopeFormatError, PackageEnvelope, encode_envelope
from layout.shape import FurnaceRow
from layout.stripe import Stripe
from layout.validate import ObservationValidationError, validate_columns, validate_shape


class PackageBuildError(ValueError):
    pass


def build_package(
    revision_id: int,
    start: int,
    stop: int,
    rows: tuple[FurnaceRow, ...],
    temperature: Stripe,
    pressure: Stripe,
) -> bytes:
    """Validate the projected shape and columns before sealing package bytes."""
    try:
        slot_count = validate_shape(rows)
        validate_columns(temperature, pressure, slot_count)
        return encode_envelope(PackageEnvelope(revision_id, start, stop, rows, temperature, pressure))
    except (ObservationValidationError, EnvelopeFormatError) as exc:
        raise PackageBuildError(str(exc)) from exc
