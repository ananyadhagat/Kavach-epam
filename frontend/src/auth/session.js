const DEVELOPMENT_TOKEN_KEY = "kavach.field-worker.development-token";
export const DEVELOPMENT_TOKEN_CHANGE_EVENT =
  "kavach.field-worker.development-token-change";

export function getDevelopmentToken() {
  try {
    return window.sessionStorage.getItem(DEVELOPMENT_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setDevelopmentToken(token) {
  const value = token.trim();

  if (!value) {
    throw new Error("Enter a development token before saving.");
  }

  try {
    window.sessionStorage.setItem(DEVELOPMENT_TOKEN_KEY, value);
    window.dispatchEvent(new Event(DEVELOPMENT_TOKEN_CHANGE_EVENT));
  } catch {
    throw new Error("This browser could not save the token for this tab.");
  }
}

export function clearDevelopmentToken() {
  try {
    window.sessionStorage.removeItem(DEVELOPMENT_TOKEN_KEY);
    window.dispatchEvent(new Event(DEVELOPMENT_TOKEN_CHANGE_EVENT));
  } catch {
    throw new Error("This browser could not clear the token for this tab.");
  }
}
