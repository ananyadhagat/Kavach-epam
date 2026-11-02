import { useEffect, useRef, useState } from "react";
import {
  getTaskEvidence,
  uploadTaskEvidence,
} from "../api/tasks.js";
import {
  EVIDENCE_MIME_TYPES,
  getEvidenceFileValidationError,
  MAX_EVIDENCE_SIZE_BYTES,
} from "../evidence/evidence-policy.js";
import Button from "./Button.jsx";
import ErrorMessage from "./ErrorMessage.jsx";
import LoadingState from "./LoadingState.jsx";
import StatusBadge from "./StatusBadge.jsx";

const ACCEPTED_IMAGE_TYPES = EVIDENCE_MIME_TYPES.join(",");
const ALLOWED_UPLOAD_STATES = new Set(["ACCEPTED", "IN_PROGRESS", "PAUSED"]);

function errorTitle(error) {
  if (error.status === 401) return "Authentication required";
  if (error.status === 403) return "Evidence access forbidden";
  if (error.status === 404) return "Task not found";
  if (error.status === 409) return "Evidence upload conflicts with task state";
  if (error.status === 413) return "Image is too large";
  if (error.status === 422) return "Image could not be accepted";
  if (error.status === 503) return "Evidence service unavailable";
  return "Could not load or upload evidence";
}

function formatUploadDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function EvidenceSection({ onEvidenceChanged, task }) {
  const [history, setHistory] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [historyError, setHistoryError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [retryNumber, setRetryNumber] = useState(0);
  const [evidenceType, setEvidenceType] = useState("BEFORE");
  const [selectedFile, setSelectedFile] = useState(null);
  const [fileError, setFileError] = useState(null);
  const [uploadError, setUploadError] = useState(null);
  const [uploadMessage, setUploadMessage] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const fileInputRef = useRef(null);
  const cameraInputRef = useRef(null);
  const historyControllerRef = useRef(null);
  const uploadControllerRef = useRef(null);
  const activeTaskIdRef = useRef(task.task_id);
  const canUpload = ALLOWED_UPLOAD_STATES.has(task.status);
  const canUploadAfter = task.status === "IN_PROGRESS";
  const canUploadSelectedType =
    canUpload && (evidenceType === "BEFORE" || canUploadAfter);

  useEffect(() => {
    if (!selectedFile) {
      setPreviewUrl(null);
      return undefined;
    }

    const objectUrl = URL.createObjectURL(selectedFile);
    setPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [selectedFile]);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    activeTaskIdRef.current = task.task_id;
    historyControllerRef.current?.abort();
    historyControllerRef.current = controller;
    setIsLoading(true);
    setIsRefreshing(false);
    setHistoryError(null);

    getTaskEvidence(task.task_id, { signal: controller.signal })
      .then((records) => {
        if (!active) return;
        setHistory(records);
        setIsLoading(false);
      })
      .catch((error) => {
        if (!active || error.name === "AbortError") return;
        setHistoryError(error);
        setIsLoading(false);
      });

    return () => {
      active = false;
      controller.abort();
      uploadControllerRef.current?.abort();
      uploadControllerRef.current = null;
      historyControllerRef.current = null;
      activeTaskIdRef.current = null;
    };
  }, [task.task_id, retryNumber]);

  function clearFileInputs() {
    if (fileInputRef.current) fileInputRef.current.value = "";
    if (cameraInputRef.current) cameraInputRef.current.value = "";
  }

  function selectFile(file, source) {
    setUploadError(null);
    setUploadMessage(null);

    if (!file) return;

    const error = getEvidenceFileValidationError(file);
    if (error) {
      setFileError(error);
      setSelectedFile(null);
      clearFileInputs();
      return;
    }

    setFileError(null);
    if (source !== "camera" && cameraInputRef.current) {
      cameraInputRef.current.value = "";
    }
    if (source !== "file" && fileInputRef.current) {
      fileInputRef.current.value = "";
    }
    setSelectedFile(file);
  }

  function selectEvidenceType(type) {
    setEvidenceType(type);
    setSelectedFile(null);
    setFileError(null);
    setUploadError(null);
    setUploadMessage(null);
    clearFileInputs();
  }

  function refreshHistory() {
    historyControllerRef.current?.abort();
    const controller = new AbortController();
    historyControllerRef.current = controller;
    setIsRefreshing(true);
    setHistoryError(null);

    getTaskEvidence(task.task_id, { signal: controller.signal })
      .then((records) => {
        if (
          controller.signal.aborted ||
          activeTaskIdRef.current !== task.task_id
        ) {
          return;
        }
        setHistory(records);
        setIsLoading(false);
      })
      .catch((error) => {
        if (
          error.name !== "AbortError" &&
          !controller.signal.aborted &&
          activeTaskIdRef.current === task.task_id
        ) {
          setHistoryError(error);
          setIsLoading(false);
        }
      })
      .finally(() => {
        if (historyControllerRef.current === controller) {
          historyControllerRef.current = null;
          setIsRefreshing(false);
        }
      });
  }

  async function submitUpload(event) {
    event.preventDefault();
    if (
      !selectedFile ||
      !canUploadSelectedType ||
      uploadControllerRef.current
    ) {
      return;
    }

    const controller = new AbortController();
    uploadControllerRef.current = controller;
    setIsUploading(true);
    setUploadError(null);
    setUploadMessage(null);

    try {
      const response = await uploadTaskEvidence(
        task.task_id,
        evidenceType,
        selectedFile,
        { signal: controller.signal },
      );

      if (
        controller.signal.aborted ||
        activeTaskIdRef.current !== task.task_id
      ) {
        return;
      }

      setUploadMessage(
        response.duplicate
          ? `${response.message} This image was already stored for this task.`
          : response.message,
      );
      setSelectedFile(null);
      setFileError(null);
      clearFileInputs();
      onEvidenceChanged?.();
      refreshHistory();
    } catch (error) {
      if (
        error.name !== "AbortError" &&
        !controller.signal.aborted &&
        activeTaskIdRef.current === task.task_id
      ) {
        setUploadError(error);
        onEvidenceChanged?.();
        refreshHistory();
      }
    } finally {
      if (uploadControllerRef.current === controller) {
        uploadControllerRef.current = null;
        setIsUploading(false);
      }
    }
  }

  return (
    <section className="evidence-panel" aria-labelledby="evidence-heading">
      <div className="evidence-panel__heading">
        <div>
          <p className="eyebrow">Task documentation</p>
          <h2 id="evidence-heading">BEFORE / AFTER photos</h2>
        </div>
        <Button
          disabled={isLoading || isRefreshing}
          onClick={refreshHistory}
          type="button"
          variant="secondary"
        >
          {isRefreshing ? "Refreshing..." : "Refresh history"}
        </Button>
      </div>

      {!canUpload && (
        <p className="evidence-guidance" role="status">
          Evidence uploads are unavailable while this task is {task.status}.
        </p>
      )}

      {canUpload && (
        <>
          <p className="evidence-guidance">
            Accepted formats: JPEG, PNG, or WebP. Maximum file size:{" "}
            {Math.round(MAX_EVIDENCE_SIZE_BYTES / (1024 * 1024))} MiB.
            Choose one method for each photo. You can replace the preview before
            uploading.
          </p>

          <form className="evidence-upload" onSubmit={submitUpload}>
            <fieldset disabled={isUploading}>
              <legend>Choose evidence type</legend>
              <div className="evidence-type-options">
                <label>
                  <input
                    checked={evidenceType === "BEFORE"}
                    name="evidence_type"
                    onChange={() => selectEvidenceType("BEFORE")}
                    type="radio"
                    value="BEFORE"
                  />
                  BEFORE
                </label>
                <label className={!canUploadAfter ? "is-disabled" : ""}>
                  <input
                    checked={evidenceType === "AFTER"}
                    disabled={!canUploadAfter}
                    name="evidence_type"
                    onChange={() => selectEvidenceType("AFTER")}
                    type="radio"
                    value="AFTER"
                  />
                  AFTER
                </label>
              </div>
            </fieldset>

            {evidenceType === "AFTER" && (
              <p className="evidence-guidance">
                AFTER photos are accepted only while the task is IN_PROGRESS.
                The backend validates the task state when you upload.
              </p>
            )}

            <div className="evidence-file-inputs">
              <Button
                disabled={isUploading || !canUploadSelectedType}
                onClick={() => cameraInputRef.current?.click()}
                type="button"
                variant="secondary"
              >
                Take Photo
              </Button>
              <Button
                disabled={isUploading || !canUploadSelectedType}
                onClick={() => fileInputRef.current?.click()}
                type="button"
                variant="secondary"
              >
                Choose File
              </Button>
              <input
                accept={ACCEPTED_IMAGE_TYPES}
                capture="environment"
                disabled={isUploading || !canUploadSelectedType}
                id="evidence-camera"
                onChange={(event) =>
                  selectFile(event.target.files?.[0], "camera")
                }
                ref={cameraInputRef}
                type="file"
                hidden
              />
              <input
                accept={ACCEPTED_IMAGE_TYPES}
                disabled={isUploading || !canUploadSelectedType}
                id="evidence-file"
                onChange={(event) => selectFile(event.target.files?.[0], "file")}
                ref={fileInputRef}
                type="file"
                hidden
              />
            </div>

            {fileError && (
              <p className="evidence-inline-error" role="alert">
                {fileError}
              </p>
            )}

            {selectedFile && (
              <div className="evidence-preview">
                {previewUrl && (
                  <img
                    alt={`Local preview of ${selectedFile.name}`}
                    src={previewUrl}
                  />
                )}
                <div className="evidence-preview__details">
                  <strong>{selectedFile.name}</strong>
                  <span>{selectedFile.type}</span>
                  <span>{selectedFile.size.toLocaleString()} bytes</span>
                  <Button
                    disabled={isUploading}
                    onClick={() => {
                      setSelectedFile(null);
                      setFileError(null);
                      clearFileInputs();
                    }}
                    type="button"
                    variant="secondary"
                  >
                    Remove selected image
                  </Button>
                </div>
              </div>
            )}

            {uploadError && (
              <ErrorMessage title={errorTitle(uploadError)}>
                {uploadError.message}
              </ErrorMessage>
            )}

            {uploadMessage && (
              <p className="evidence-success" role="status">
                {uploadMessage}
              </p>
            )}

            {isUploading && (
              <div className="evidence-upload-progress" role="status">
                <span>Uploading {evidenceType} photo...</span>
                <progress aria-label={`Uploading ${evidenceType} photo`} />
              </div>
            )}

            <Button
              disabled={!selectedFile || !canUploadSelectedType || isUploading}
              type="submit"
            >
              {isUploading ? "Uploading..." : "Upload evidence"}
            </Button>
          </form>
        </>
      )}

      <section className="evidence-history" aria-labelledby="evidence-history-heading">
        <div className="evidence-history__heading">
          <div>
            <h3 id="evidence-history-heading">Evidence history</h3>
            <p className="evidence-guidance">
              Stored records are loaded from this task's backend history. A new
              photo appears above as a local preview until it is uploaded.
            </p>
          </div>
          {history.length > 0 && (
            <span>
              {history.length} {history.length === 1 ? "record" : "records"}
            </span>
          )}
        </div>

        {isLoading && <LoadingState label="Loading evidence history..." />}

        {historyError && (
          <div className="evidence-history__error">
            <ErrorMessage title={errorTitle(historyError)}>
              {historyError.message}
            </ErrorMessage>
            <Button
              onClick={() => setRetryNumber((current) => current + 1)}
              type="button"
              variant="secondary"
            >
              Retry history
            </Button>
          </div>
        )}

        {!isLoading && !historyError && history.length === 0 && (
          <p className="evidence-history__empty">
            No evidence has been uploaded for this task.
          </p>
        )}

        {history.length > 0 && (
          <ol className="evidence-history__list">
            {history.map((item, index) => (
              <li
                className="evidence-history__item"
                key={`${item.evidence_type}-${item.uploaded_at}-${index}`}
              >
                <div className="evidence-history__item-heading">
                  <StatusBadge status={item.evidence_type} />
                  {item.status && <span>{item.status}</span>}
                  <span>
                    {item.worker_id === task.assigned_worker_id
                      ? "Current worker record"
                      : "Previous worker record"}
                  </span>
                </div>
                <dl>
                  <div>
                    <dt>Filename</dt>
                    <dd>{item.original_filename}</dd>
                  </div>
                  <div>
                    <dt>Uploaded</dt>
                    <dd>
                      <time dateTime={item.uploaded_at}>
                        {formatUploadDate(item.uploaded_at)}
                      </time>
                    </dd>
                  </div>
                  <div>
                    <dt>File type</dt>
                    <dd>{item.mime_type}</dd>
                  </div>
                  <div>
                    <dt>Size</dt>
                    <dd>{item.size_bytes.toLocaleString()} bytes</dd>
                  </div>
                </dl>
                <p className="evidence-history__notice">
                  Stored records are metadata only; previous images cannot be
                  previewed or downloaded.
                </p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </section>
  );
}
