from archive.envelope import EnvelopeFormatError, decode_envelope
from layout.stripe import StripeError
from review.assemble import assemble_result
from review.result import ReviewResult
from review.validate import PackageValidationError, validate_package


def read_package(payload: bytes) -> ReviewResult:
    """Validate and read a detached package without accessing the source catalog."""
    try:
        package = decode_envelope(payload)
        slot_count = validate_package(package)
        return assemble_result(package, slot_count)
    except (EnvelopeFormatError, StripeError) as exc:
        raise PackageValidationError(str(exc)) from exc
