const DEFAULT_SITE_URL = "http://localhost:3000";

export function getSiteUrl() {
  const configuredUrl = process.env.NEXT_PUBLIC_APP_URL?.trim() || DEFAULT_SITE_URL;

  try {
    const url = new URL(configuredUrl);

    if (url.protocol === "http:" || url.protocol === "https:") {
      return url.origin;
    }
  } catch {
    // Fall back to the public production domain when the environment value is invalid.
  }

  return DEFAULT_SITE_URL;
}

export function getPublicUrl(pathname: string) {
  return new URL(pathname, getSiteUrl()).toString();
}
