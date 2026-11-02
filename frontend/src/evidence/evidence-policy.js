export const MAX_EVIDENCE_SIZE_BYTES = 5 * 1024 * 1024;
export const EVIDENCE_MIME_TYPES = [
  "image/jpeg",
  "image/png",
  "image/webp",
];

export function getEvidenceFileValidationError(file) {
  if (!file || !Number.isFinite(file.size) || file.size < 1) {
    return "The selected image is empty. Choose another image.";
  }

  if (file.size > MAX_EVIDENCE_SIZE_BYTES) {
    return "Choose an image no larger than 5 MiB.";
  }

  if (
    typeof file.type !== "string" ||
    !EVIDENCE_MIME_TYPES.includes(file.type.toLowerCase())
  ) {
    return "Choose a JPEG, PNG, or WebP image.";
  }

  return null;
}
