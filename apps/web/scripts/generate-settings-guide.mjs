// Writes docs/user-guide/SETTINGS_GUIDE.md from the same content the in-app Settings Guide shows.
// Usage: npm run guide:docs
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../src/lib/settings-guide/content.json");
const target = resolve(here, "../../../docs/user-guide/SETTINGS_GUIDE.md");

const { overview, sections } = JSON.parse(readFileSync(source, "utf8"));
const lines = [];
const add = (...l) => lines.push(...l);

add(
  "# Settings Guide",
  "",
  "<!-- Generated from apps/web/src/lib/settings-guide/content.json by `npm run guide:docs`. Edit the JSON, not this file. -->",
  "",
  "What each setting is, what every option does, and how to use it, in plain English.",
  "",
  "## Contents",
  "",
  "- [How the settings fit together](#how-the-settings-fit-together)",
);
let group = null;
for (const s of sections) {
  if (s.group !== group) {
    group = s.group;
    add(`- **${group}**`);
  }
  add(`  - [${s.title}](#${s.id})`);
}
add("", `## ${overview.title}`, "");
for (const p of overview.paragraphs) add(p, "");
add(`### ${overview.stepsTitle}`, "");
overview.steps.forEach((step, i) => add(`${i + 1}. ${step}`));
add("", "### Words used throughout", "");
for (const g of overview.glossary) add(`- **${g.term}**: ${g.text}`);
add("");

group = null;
for (const s of sections) {
  if (s.group !== group) {
    group = s.group;
    add(`# ${group}`, "");
  }
  add(`<a id="${s.id}"></a>`, `## ${s.title}`, "", s.summary, "", `**When to use it:** ${s.whenToUse}`, "");
  for (const part of s.parts) {
    add(`### ${part.title}`, "");
    if (part.intro) add(part.intro, "");
    for (const item of part.items) add(`- **${item.name}:** ${item.text}`);
    add("");
  }
  if (s.example) add(`**Example:** ${s.example}`, "");
  if (s.tips.length) {
    add("**Good to know**", "");
    for (const tip of s.tips) add(`- ${tip}`);
    add("");
  }
}

writeFileSync(target, lines.join("\n").replace(/\n{3,}/g, "\n\n"));
console.log(`Wrote ${target}`);
