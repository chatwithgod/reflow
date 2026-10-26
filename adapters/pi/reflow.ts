import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

// Endpoint-only override: Pi keeps its catalog, OAuth login, refresh and wire API.
// Deliberately scoped to Pi's openai-codex provider; other providers are untouched.
export default function reflow(pi: ExtensionAPI) {
  const url = new URL(process.env.REFLOW_URL ?? "http://127.0.0.1:18516");
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) ||
    url.username || url.password || url.search || url.hash || url.pathname !== "/"
  ) {
    throw new Error("REFLOW_URL must be a loopback HTTP origin, for example http://127.0.0.1:18516");
  }
  pi.registerProvider("openai-codex", { baseUrl: `${url.origin}/backend-api` });
}
