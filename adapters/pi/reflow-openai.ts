import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
// Pi 1.4's extension loader exposes its pi-ai compatibility exports here.
import { openAIResponsesApi } from "@earendil-works/pi-ai";
import { PUBLIC_BASE, loopbackOrigin, reflowResponsesFetch } from "./lib/openai-transport.mjs";

// Keep the canonical model URL: Pi uses it to apply ChatGPT sign-in restrictions.
// Reuse Pi's payload, auth, retry, stream parser and usage handling unchanged.
export default function reflowOpenAI(pi: ExtensionAPI) {
  const openAI = openAIResponsesApi();
  const origin = loopbackOrigin(process.env.REFLOW_URL ?? "http://127.0.0.1:18517");
  pi.registerProvider("openai", {
    api: "openai-responses",
    streamSimple(model, context, options) {
      if (model.provider !== "openai") return openAI.streamSimple(model, context, options);
      if (model.baseUrl !== PUBLIC_BASE) {
        throw new Error("Reflow OpenAI adapter requires the canonical OpenAI model URL; remove conflicting endpoint overrides");
      }
      return openAI.streamSimple(model, context, {
        ...options,
        fetch: reflowResponsesFetch(origin, options?.fetch ?? globalThis.fetch),
      });
    },
  });
}
