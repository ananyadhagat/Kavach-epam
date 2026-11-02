import { getDevelopmentToken } from "../auth/session.js";
import { ApiError, makeApiError } from "./errors.js";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000/api/v1";
const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const API_BASE_URL = (configuredBaseUrl || DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  "",
);

function makeRequestUrl(path) {
  return `${API_BASE_URL}/${path.replace(/^\/+/, "")}`;
}

export async function apiRequest(path, options = {}) {
  const { body, headers: providedHeaders = {}, ...requestOptions } = options;
  const headers = new Headers(providedHeaders);
  const token = getDevelopmentToken();

  headers.delete("Authorization");
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let requestBody = body;

  if (
    body !== undefined &&
    body !== null &&
    !(body instanceof FormData) &&
    typeof body !== "string"
  ) {
    headers.set("Content-Type", "application/json");
    requestBody = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(makeRequestUrl(path), {
      ...requestOptions,
      headers,
      body: requestBody,
    });
  } catch (cause) {
    if (cause?.name === "AbortError") {
      throw cause;
    }

    throw new ApiError(
      "Could not reach the Field Worker API. Check the backend URL and network connection.",
      { cause },
    );
  }

  if (!response.ok) {
    throw await makeApiError(response, token);
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new ApiError(
      `The server returned an unexpected response (${response.status}).`,
      { status: response.status },
    );
  }

  try {
    return await response.json();
  } catch (cause) {
    throw new ApiError("The server returned invalid JSON.", {
      status: response.status,
      cause,
    });
  }
}

export function getApiBaseUrl() {
  return API_BASE_URL;
}
