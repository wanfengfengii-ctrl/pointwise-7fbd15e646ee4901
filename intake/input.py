from dataclasses import dataclass

from layout.shape import FurnaceRow, ShapeError, parse_shape
from layout.stripe import Stripe, StripeError, parse_stripe


class SubmissionInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BatchSubmission:
    batch_id: str
    declared_revision: str
    rows: tuple[FurnaceRow, ...]
    temperature: Stripe
    pressure: Stripe


def _label(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SubmissionInputError(f'{field} must be nonempty text')
    try:
        raw.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise SubmissionInputError(f'{field} is not UTF-8 text') from exc
    return raw


def parse_submission(raw: object) -> BatchSubmission:
    fields = {'batch_id', 'revision', 'rows', 'temperature', 'pressure'}
    if not isinstance(raw, dict) or raw.keys() != fields:
        raise SubmissionInputError('submission needs batch_id, revision, rows, temperature and pressure')
    batch_id = _label(raw['batch_id'], 'batch_id')
    declared_revision = _label(raw['revision'], 'revision')
    try:
        rows = parse_shape(raw['rows'])
        temperature = parse_stripe(raw['temperature'])
        pressure = parse_stripe(raw['pressure'])
    except (ShapeError, StripeError) as exc:
        raise SubmissionInputError(str(exc)) from exc
    return BatchSubmission(batch_id, declared_revision, rows, temperature, pressure)
