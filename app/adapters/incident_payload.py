"""Adapter from Agent 1's draft duplicate-detection handoff to ``Complaint``.

The Incident Intelligence Agent owns the upstream mapping from its
``StructuredIncidentRecord`` to the draft handoff payload. Its handoff module
(``origin/incident-intelligence-agent:src/kavach/services/incident_intelligence/
handoff.py``, contract version ``a1-to-a2-draft-1``) already emits the V1 field
names used by this project:

* ``complaint_id`` <- ``incident_id``
* ``description`` <- ``complaint_text`` (fallback ``incident_summary``)
* ``category`` <- ``incident_type`` unless ``UNKNOWN``, else ``category``
* ``reported_at`` <- ``submitted_at`` (fallback ``created_at``)
* ``location`` <- ``reported_incident_location`` only
* ``image_hash`` <- the first accepted image's ``perceptual_hash``

This adapter deliberately does **not** re-implement that mapping. It validates
the handoff envelope, drops the documented ``kavach_agent1`` context object, and
constructs the existing :class:`app.schemas.complaint.Complaint` model. Keeping
the upstream mapping in one place avoids two competing interpretations of
``created_at``/``reported_at`` and ``complaint_text``/``incident_summary``.

The handoff contract is still provisional. Raw ``StructuredIncidentRecord``
field names are rejected at this boundary so an unmapped or renamed upstream
field fails loudly instead of being silently ignored or guessed. The only
allowed non-``Complaint`` top-level key is ``kavach_agent1``, which the handoff
documentation explicitly says Agent 2 may ignore.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.schemas.complaint import Complaint

#: Draft handoff version this adapter was written against.
HANDOFF_CONTRACT_VERSION = "a1-to-a2-draft-1"

#: Canonical fields accepted by ``Complaint``. Order is used in error messages.
_COMPLAINT_FIELDS: tuple[str, ...] = (
    "complaint_id",
    "description",
    "category",
    "location",
    "reported_at",
    "image_hash",
)
_COMPLAINT_FIELD_SET = frozenset(_COMPLAINT_FIELDS)

#: Agent 1 context that the handoff contract says Agent 2 may ignore.
_IGNORED_CONTEXT_FIELDS = frozenset({"kavach_agent1"})


class IncidentPayloadError(ValueError):
    """Raised when the handoff envelope is not the agreed shape.

    Field-level problems (missing id, bad timestamp, invalid coordinates) are
    left to Pydantic and surface as :class:`pydantic.ValidationError`.
    """

    def __init__(
        self,
        message: str,
        *,
        unsupported_fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.unsupported_fields = unsupported_fields


def to_complaint(payload: Mapping[str, object]) -> Complaint:
    """Convert an Agent 1 handoff payload into the existing ``Complaint``.

    Parameters
    ----------
    payload:
        Mapping produced by Agent 1's
        ``build_duplicate_detection_request()``. It must use the canonical
        handoff keys, not the raw ``StructuredIncidentRecord`` keys.

    Returns
    -------
    Complaint
        The existing internal model, fully validated.

    Raises
    ------
    IncidentPayloadError
        If ``payload`` is not a mapping or contains unsupported top-level
        fields. ``kavach_agent1`` is allowed and ignored.
    pydantic.ValidationError
        If a supported field has an invalid value or a required field is
        missing.
    """
    if not isinstance(payload, Mapping):
        raise IncidentPayloadError(
            "incident handoff payload must be a mapping, "
            f"got {type(payload).__name__}"
        )

    unsupported = tuple(
        sorted(
            str(key)
            for key in payload
            if key not in _COMPLAINT_FIELD_SET
            and key not in _IGNORED_CONTEXT_FIELDS
        )
    )
    if unsupported:
        raise IncidentPayloadError(
            "unsupported incident handoff field(s): "
            + ", ".join(unsupported)
            + ". Supported fields: "
            + ", ".join(_COMPLAINT_FIELDS)
            + "; 'kavach_agent1' is ignored.",
            unsupported_fields=unsupported,
        )

    # Copy only the canonical fields so the ignored context object never reaches
    # ``Complaint`` (which forbids extra fields).
    data = {field: payload[field] for field in _COMPLAINT_FIELDS if field in payload}
    return Complaint.model_validate(data)
