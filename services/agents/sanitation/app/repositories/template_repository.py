import threading
from typing import Protocol
from app.policies.template_registry import SAN_TEMPLATES, SanitationTemplate


class TemplateRepository(Protocol):
    """Protocol for template retrieval."""

    def get(self, template_id: str, version: str = "1") -> SanitationTemplate | None:
        ...

    def list_all(self) -> list[SanitationTemplate]:
        ...


class InMemoryTemplateRepository:
    """In-memory template repository backed by process memory.

    Note: Holds approved templates in memory; does not survive process restart.
    """

    def __init__(self, initial_templates: dict[tuple[str, str], SanitationTemplate] | None = None):
        self._templates: dict[tuple[str, str], SanitationTemplate] = (
            dict(initial_templates) if initial_templates is not None else dict(SAN_TEMPLATES)
        )
        self._lock = threading.Lock()

    def get(self, template_id: str, version: str = "1") -> SanitationTemplate | None:
        with self._lock:
            return self._templates.get((template_id, str(version)))

    def list_all(self) -> list[SanitationTemplate]:
        with self._lock:
            return list(self._templates.values())

    def register(self, template: SanitationTemplate) -> None:
        with self._lock:
            self._templates[(template.template_id, str(template.template_version))] = template

    def clear(self) -> None:
        with self._lock:
            self._templates.clear()


# Default singleton instance
template_repo = InMemoryTemplateRepository()
