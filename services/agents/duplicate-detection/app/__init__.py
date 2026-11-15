"""KAVACH Duplicate Detection Agent — standalone prototype package.

The core pipeline is implemented under ``app/``: schemas, repository,
comparators, weighted scoring, decision policy, the internal orchestration
service, and the Agent 3 HTTP edge. See
``docs/duplicate_detection/service_orchestration.md`` and
``docs/duplicate_detection/m3_http_contract.md`` for the current map.
"""

__all__ = ["__version__"]

__version__ = "0.2.0"
