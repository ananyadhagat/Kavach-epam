import assert from "node:assert/strict";
import test from "node:test";
import {
  EVIDENCE_MIME_TYPES,
  getEvidenceFileValidationError,
  MAX_EVIDENCE_SIZE_BYTES,
} from "../src/evidence/evidence-policy.js";

test("accepts JPEG, PNG and WebP files within the configured limit", () => {
  for (const type of EVIDENCE_MIME_TYPES) {
    assert.equal(
      getEvidenceFileValidationError({ size: 1024, type }),
      null,
    );
  }
});

test("accepts a file exactly at the 5 MiB limit", () => {
  assert.equal(
    getEvidenceFileValidationError({
      size: MAX_EVIDENCE_SIZE_BYTES,
      type: "image/jpeg",
    }),
    null,
  );
});

test("rejects empty or unsupported image files with actionable errors", () => {
  assert.match(
    getEvidenceFileValidationError({ size: 0, type: "image/jpeg" }),
    /empty/i,
  );
  assert.match(
    getEvidenceFileValidationError({ size: 1, type: "image/gif" }),
    /JPEG, PNG, or WebP/i,
  );
});

test("rejects files larger than 5 MiB", () => {
  assert.match(
    getEvidenceFileValidationError({
      size: MAX_EVIDENCE_SIZE_BYTES + 1,
      type: "image/jpeg",
    }),
    /no larger than 5 MiB/i,
  );
});
