from intake.input import BatchSubmission
from layout.validate import ObservationValidationError, validate_columns, validate_shape


class RegistrationValidationError(ValueError):
    pass


def validate_submission(submission: BatchSubmission) -> None:
    try:
        slot_count = validate_shape(submission.rows)
        validate_columns(submission.temperature, submission.pressure, slot_count)
    except ObservationValidationError as exc:
        raise RegistrationValidationError(str(exc)) from exc
