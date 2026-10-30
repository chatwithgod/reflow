import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { realpathSync } from "node:fs";
import { resolve } from "node:path";

// Evaluation only: one read of a generated fixture, no other model tools.
export default function probeGuard(pi: ExtensionAPI) {
  const fixture = realpathSync(resolve(process.cwd(), "probe.txt"));
  let allowed = 0;
  let blocked = 0;
  const report = () => process.stdout.write(`${JSON.stringify({ type: "reflow_probe_guard", version: 1, allowed, blocked })}\n`);
  pi.on("tool_call", (event, ctx) => {
    let valid = false;
    try {
      valid = event.toolName === "read" && typeof event.input.path === "string" &&
        realpathSync(resolve(process.cwd(), event.input.path)) === fixture && allowed === 0;
    } catch { /* Fail closed without emitting the requested path. */ }
    if (valid) allowed++;
    else blocked++;
    report();
    if (!valid) {
      ctx.abort();
      return { block: true, reason: "REFLOW_PI_PROBE_TOOL_BLOCKED" };
    }
  });
  pi.on("agent_end", report);
}
