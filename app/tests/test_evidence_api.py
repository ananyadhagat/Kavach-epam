import hashlib
import re
from pathlib import Path

import pytest
from PIL import Image

from app.config import settings
from app.schemas.worker_task import TaskStatus
from app.services.evidence_service import safe_display_filename
from app.tests.conftest import (
    API,
    AUTH,
    OTHER_WORKER_ID,
    add_task,
    complete_checklist,
    evidence_records,
    make_image,
    make_task,
    post_action,
    set_status,
    upload,
)

STORAGE_KEY = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")


@pytest.fixture
def accepted(client):
    return client


def stored_files(upload_dir: Path) -> list[Path]:
    if not upload_dir.exists():
        return []
    return sorted(p for p in upload_dir.rglob("*") if p.is_file())


def assert_nothing_stored(client, upload_dir: Path):
    assert stored_files(upload_dir) == []
    assert evidence_records(client) == {}


@pytest.mark.parametrize(
    ("fmt", "mime", "suffix"),
    [
        ("JPEG", "image/jpeg", ".jpg"),
        ("PNG", "image/png", ".png"),
        ("WEBP", "image/webp", ".webp"),
    ],
)
def test_valid_upload(accepted, upload_dir, fmt, mime, suffix):
    content = make_image(fmt)

    response = upload(
        accepted, "TASK-001", "BEFORE", content=content,
        content_type=mime, filename=f"before{suffix}",
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["duplicate"] is False
    assert body["message"] == "Image validated and stored."

    evidence = body["evidence"]
    assert evidence["task_id"] == "TASK-001"
    assert evidence["worker_id"] == "worker-001"
    assert evidence["evidence_type"] == "BEFORE"
    assert evidence["mime_type"] == mime
    assert evidence["size_bytes"] == len(content)
    assert evidence["sha256"] == hashlib.sha256(content).hexdigest()
    assert evidence["status"] == "STORED"
    assert STORAGE_KEY.match(evidence["storage_key"])
    assert evidence["storage_key"].endswith(suffix)

    files = stored_files(upload_dir)
    assert [f.name for f in files] == [evidence["storage_key"]]
    assert files[0].read_bytes() == content
    # Atomic write leaves no temporary files behind.
    assert not any(f.name.startswith(".tmp-") for f in files)


@pytest.mark.parametrize("state", [["start"],
                                   ["start", "pause"]])
def test_upload_allowed_while_working(client, state):
    for action in state:
        post_action(client, "TASK-001", action)

    # Differs from the BEFORE image uploaded by the start helper, so this
    # stores a new record instead of reusing a duplicate.
    response = upload(client, "TASK-001", content=make_image(color="red"))

    assert response.status_code == 200
    assert response.json()["duplicate"] is False


def test_file_larger_than_5_mb(accepted, upload_dir):
    content = b"\x89PNG" + b"0" * (5 * 1024 * 1024)

    response = upload(accepted, "TASK-001", content=content)

    assert response.status_code == 413
    assert response.json() == {"detail": "Image exceeds the allowed size limit."}
    assert_nothing_stored(accepted, upload_dir)


def test_size_limit_boundary(accepted, upload_dir, monkeypatch):
    content = make_image("PNG")
    monkeypatch.setattr(settings, "max_image_size_bytes", len(content))

    assert upload(accepted, "TASK-001", content=content).status_code == 200

    monkeypatch.setattr(settings, "max_image_size_bytes", len(content) - 1)
    # The size limit is checked before duplicate detection, so re-sending
    # the same image is rejected as oversized rather than reused.
    response = upload(accepted, "TASK-001", "BEFORE", content=content)
    assert response.status_code == 413
    assert len(evidence_records(accepted)) == 1


@pytest.mark.parametrize(
    ("content_type", "content"),
    [
        ("image/gif", make_image("GIF")),
        ("image/bmp", make_image("BMP")),
        ("text/plain", b"hello"),
        ("application/pdf", b"%PDF-1.4"),
        ("application/octet-stream", make_image("PNG")),
    ],
    ids=["gif", "bmp", "text", "pdf", "octet-stream"],
)
def test_unsupported_media_type(accepted, upload_dir, content_type, content):
    response = upload(accepted, "TASK-001", content=content,
                      content_type=content_type)

    assert response.status_code == 422
    assert response.json() == {"detail": "Unsupported MIME type."}
    assert_nothing_stored(accepted, upload_dir)


def test_empty_file(accepted, upload_dir):
    response = upload(accepted, "TASK-001", content=b"")

    assert response.status_code == 422
    assert_nothing_stored(accepted, upload_dir)


@pytest.mark.parametrize(
    "content",
    [
        b"this is not an image",
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 50,
        make_image("PNG")[:40],
    ],
    ids=["text", "png-signature-garbage", "truncated-png"],
)
def test_malformed_content(accepted, upload_dir, content):
    response = upload(accepted, "TASK-001", content=content)

    assert response.status_code == 422
    assert "not a valid" in response.json()["detail"]
    assert_nothing_stored(accepted, upload_dir)


def test_declared_type_must_match_content(accepted, upload_dir):
    response = upload(accepted, "TASK-001", content=make_image("JPEG"),
                      content_type="image/png")

    assert response.status_code == 422
    assert "does not match" in response.json()["detail"]
    assert_nothing_stored(accepted, upload_dir)


def test_decompression_bomb_is_rejected(accepted, upload_dir, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 50)

    response = upload(accepted, "TASK-001",
                      content=make_image("PNG", size=(100, 100)))

    assert response.status_code == 422
    assert "safe decoding limit" in response.json()["detail"]
    assert_nothing_stored(accepted, upload_dir)


@pytest.mark.parametrize(
    "filename",
    [
        "../../evil.png",
        "..\\..\\evil.png",
        "C:\\Windows\\System32\\evil.png",
        "/etc/passwd",
        "..",
        "evil\x00.png",
        "sub/dir/evil.png",
    ],
)
def test_unsafe_filename_cannot_escape_storage(accepted, upload_dir,
                                              tmp_path, filename):
    response = upload(accepted, "TASK-001", filename=filename)

    assert response.status_code == 200, response.text
    evidence = response.json()["evidence"]

    # Storage key is a random name, never derived from the client.
    assert STORAGE_KEY.match(evidence["storage_key"])
    assert "/" not in evidence["original_filename"]
    assert "\\" not in evidence["original_filename"]
    assert not evidence["original_filename"].startswith(".")

    files = stored_files(upload_dir)
    assert len(files) == 1
    assert files[0].parent == upload_dir.resolve()
    # Nothing was written anywhere else in the test's temp area.
    outside = [p for p in tmp_path.rglob("*")
               if p.is_file() and upload_dir not in p.parents]
    assert outside == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../evil.png", "evil.png"),
        ("..\\a\\b.jpg", "b.jpg"),
        ("..", "upload"),
        ("", "upload"),
        (None, "upload"),
        (".hidden.png", "hidden.png"),
        ("a\x00b\x1f.png", "ab.png"),
        ("x" * 300 + ".png", "x" * 255),
    ],
)
def test_safe_display_filename(raw, expected):
    assert safe_display_filename(raw) == expected


def test_storage_rejects_traversal_keys(client):
    storage = client.app.state.evidence_service.storage

    for key in ("../outside.png", "..\\outside.png", "a/b.png"):
        with pytest.raises(ValueError):
            storage.resolve(key)


def test_upload_to_nonexistent_task(client, upload_dir):
    response = upload(client, "NOPE")

    assert response.status_code == 404
    assert_nothing_stored(client, upload_dir)


def test_upload_to_other_workers_task(client, upload_dir):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID,
                               status=TaskStatus.ACCEPTED))

    response = upload(client, "OTHER-1")

    assert response.status_code == 404
    assert_nothing_stored(client, upload_dir)


def test_evidence_history_requires_worker_authentication(client):
    response = client.get(f"{API}/TASK-001/evidence")

    assert response.status_code == 401


def test_evidence_history_hides_other_workers_tasks(client):
    add_task(client, make_task("OTHER-1", worker_id=OTHER_WORKER_ID))

    response = client.get(f"{API}/OTHER-1/evidence",
                          headers=AUTH)

    assert response.status_code == 404


def test_evidence_history_is_empty_for_task_without_evidence(client):
    response = client.get(f"{API}/TASK-001/evidence",
                          headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"task_id": "TASK-001", "evidence": []}


def test_evidence_history_returns_all_records_without_storage_details(client):
    start_before = upload(client, "TASK-001", "BEFORE").json()["evidence"]
    before_one = upload(client, "TASK-001", "BEFORE",
                        content=make_image(color="red")).json()["evidence"]
    before_two = upload(client, "TASK-001", "BEFORE",
                        content=make_image(color="blue")).json()["evidence"]
    assert post_action(client, "TASK-001", "start").status_code == 200
    complete_checklist(client, "TASK-001")
    after_one = upload(client, "TASK-001", "AFTER",
                       content=make_image(color="black")).json()["evidence"]
    after_two = upload(client, "TASK-001", "AFTER",
                       content=make_image(color="green")).json()["evidence"]

    response = client.get(f"{API}/TASK-001/evidence",
                          headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == "TASK-001"
    records = body["evidence"]
    assert {record["evidence_id"] for record in records} == {
        start_before["evidence_id"],
        before_one["evidence_id"],
        before_two["evidence_id"],
        after_one["evidence_id"],
        after_two["evidence_id"],
    }
    assert len(records) == 5
    assert [record["evidence_type"] for record in records].count("BEFORE") == 3
    assert [record["evidence_type"] for record in records].count("AFTER") == 2
    ordering = [
        (record["uploaded_at"], record["evidence_id"]) for record in records
    ]
    assert ordering == sorted(ordering)
    assert all(record["status"] == "STORED" for record in records)
    assert all(set(record) == {
        "evidence_id",
        "task_id",
        "worker_id",
        "evidence_type",
        "original_filename",
        "mime_type",
        "size_bytes",
        "status",
        "uploaded_at",
    } for record in records)


@pytest.mark.parametrize("status", ["ASSIGNED", "REJECTED", "BLOCKED"])
def test_upload_not_allowed_in_state(client, upload_dir, status):
    set_status(client, "TASK-001", status)

    response = upload(client, "TASK-001")

    assert response.status_code == 409
    assert_nothing_stored(client, upload_dir)


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong-token"}],
    ids=["missing", "wrong"],
)
def test_unauthorized_upload(accepted, upload_dir, headers):
    response = upload(accepted, "TASK-001", headers=headers)

    assert response.status_code == 401
    assert_nothing_stored(accepted, upload_dir)


def test_invalid_evidence_type(accepted, upload_dir):
    response = upload(accepted, "TASK-001", evidence_type="DURING")

    assert response.status_code == 422
    assert_nothing_stored(accepted, upload_dir)


def test_missing_file_field(accepted, upload_dir):
    from app.tests.conftest import AUTH

    response = accepted.post(
        f"{API}/TASK-001/evidence", data={"evidence_type": "BEFORE"},
        headers=AUTH,
    )

    assert response.status_code == 422
    assert_nothing_stored(accepted, upload_dir)


def test_duplicate_upload_reuses_record_and_file(accepted, upload_dir):
    first = upload(accepted, "TASK-001", filename="a.png")
    second = upload(accepted, "TASK-001", filename="retry.png")

    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["message"] == "Existing evidence reused."
    assert (second.json()["evidence"]["evidence_id"]
            == first.json()["evidence"]["evidence_id"])
    assert len(stored_files(upload_dir)) == 1
    assert len(evidence_records(accepted)) == 1


def test_same_image_as_different_type_is_new_record(accepted, upload_dir):
    content = make_image("PNG")

    before = upload(accepted, "TASK-001", "BEFORE", content=content)
    # AFTER evidence needs started work with the required checklist done.
    assert post_action(accepted, "TASK-001", "start").status_code == 200
    complete_checklist(accepted, "TASK-001")
    after = upload(accepted, "TASK-001", "AFTER", content=content)

    assert after.json()["duplicate"] is False
    assert (before.json()["evidence"]["evidence_id"]
            != after.json()["evidence"]["evidence_id"])
    assert len(stored_files(upload_dir)) == 2
