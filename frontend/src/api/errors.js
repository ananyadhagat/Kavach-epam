const STATUS_MESSAGES = {
  401: "Authentication required. Configure a local development token.",
  403: "You do not have permission to perform this action.",
  404: "The requested resource could not be found.",
  409: "The request conflicts with the current task state.",
  413: "The uploaded file is too large.",
  422: "Some request information is invalid.",
  503: "The service or required configuration is currently unavailable.",
};

export class ApiError extends Error {
  constructor(message, { status = null, cause } = {}) {
    super(message, { cause });
    this.name = "ApiError";
    this.status = status;
  }
}

function redactSensitiveText(value, token) {
  let message = value;

  if (token) {
    message = message.replaceAll(token, "[redacted]");
  }

  return message
    .replace(/Bearer\s+\S+/gi, "Bearer [redacted]")
    .replace(
      /(token|secret|password|api[_-]?key)\s*[:=]\s*["']?[^,\s"']+/gi,
      "$1=[redacted]",
    );
}

function responseDetail(payload, token) {
  const detail = payload?.detail;
  let message;

  if (typeof detail === "string") {
    message = detail;
  } else if (Array.isArray(detail)) {
    message = detail
      .map((item) => {
        if (typeof item?.msg !== "string") {
          return null;
        }

        const location = Array.isArray(item.loc)
          ? item.loc
              .filter((part) => typeof part === "string" || Number.isInteger(part))
              .join(".")
          : "";
        return location ? `${location}: ${item.msg}` : item.msg;
      })
      .filter((item) => typeof item === "string")
      .join("; ");
  }

  if (!message) {
    return null;
  }

  if (/traceback|stack trace|file ["'].*line \d+/i.test(message)) {
    return null;
  }

  return redactSensitiveText(message, token).slice(0, 500);
}

export async function makeApiError(response, token) {
  const fallback =
    STATUS_MESSAGES[response.status] ??
    `The server returned an unexpected response (${response.status}).`;

  let detail = null;
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    try {
      detail = responseDetail(await response.json(), token);
    } catch {
      detail = null;
    }
  }

  const message =
    detail && detail !== fallback ? `${fallback} ${detail}` : fallback;

  return new ApiError(message, { status: response.status });
}
