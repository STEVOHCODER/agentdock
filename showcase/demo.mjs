#!/usr/bin/env node
// Honest demo: this script only talks to the public AgentDock marketplace.
// It does not hard-code skill knowledge; it reads the gateway and prints it.
import { search } from "./agentdock-api.mjs";

const result = await search("frontend");
console.log("total", result.total);
for (const item of result.items.slice(0, 5)) {
  console.log(item.name, "|", item.category, "|", item.slug, "|", item.stars);
}
