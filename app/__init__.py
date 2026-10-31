"""KAVACH Duplicate Detection Agent — standalone prototype package.

The core pipeline is implemented under ``app/``: schemas, repository,
comparators, weighted scoring, decision policy and the internal orchestration
service. The FastAPI/HTTP edge remains deferred; see
``docs/duplicate_detection/service_orchestration.md`` for the current map.
"""

__all__ = ["__version__"]

__version__ = "0.2.0"
