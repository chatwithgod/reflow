export const PUBLIC_BASE = "https://api.openai.com/v1";

export function loopbackOrigin(value) {
  const url = new URL(value);
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
    url.username || url.password || url.search || url.hash || url.pathname !== "/"
  ) {
    throw new Error("REFLOW_URL must be a loopback HTTP origin, for example http://127.0.0.1:18517");
  }
  return url.origin;
}

export function reflowResponsesFetch(origin, next = globalThis.fetch) {
  const target = loopbackOrigin(origin);
  return async (input, init) => {
    const request = new Request(input, init);
    const url = new URL(request.url);
    if (request.method !== "POST" || url.origin !== "https://api.openai.com" || url.pathname !== "/v1/responses") {
      throw new Error("Reflow OpenAI adapter only forwards public Responses requests");
    }
    const destination = new URL(`${url.pathname}${url.search}`, target);
    return next(new Request(destination, request));
  };
}
