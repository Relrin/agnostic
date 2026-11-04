// License policy check for frontend dependencies. Walks the production dependency graph of what ships
// (the @agnostic/web app, through the workspace packages it uses) and checks every package's `license` field.
// Dev tooling never ships, so devDependencies are skipped. Fails on forbidden or unknown licenses and on weak
// copyleft that hasn't been reviewed into WEAK_ALLOWED. `--write FILE` also writes the third-party notices (name,
// version, license and the license files each package ships) for the web build; the image carries it in /licenses.
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("..", import.meta.url));

const PERMISSIVE = /\b(MIT|ISC|BSD|Apache|0BSD|Unlicense|CC0|CC-BY-4\.0|Python-2\.0|BlueOak|Zlib|OFL)\b/i;
const WEAK = /\b(MPL|LGPL|EPL)\b/i;
const FORBIDDEN = /\b(AGPL|SSPL|BUSL|BSL|RSAL|Commons Clause)\b|\bGPL\b/i;

/** Weak-copyleft packages reviewed and allowed unmodified (name → license). Adding one needs a reviewer. */
const WEAK_ALLOWED = { elkjs: "EPL-2.0" };

function readManifest(directory) {
  return JSON.parse(readFileSync(join(directory, "package.json"), "utf8"));
}

/** Directory of `name` as resolved from `fromDirectory` (walks up node_modules like Node does). */
function resolvePackage(name, fromDirectory) {
  const require = createRequire(join(fromDirectory, "package.json"));
  for (const base of require.resolve.paths(name) ?? []) {
    try {
      const candidate = join(base, name);
      readManifest(candidate);
      return candidate;
    } catch {
      // keep walking up
    }
  }
  return undefined;
}

function licenseOf(manifest) {
  if (typeof manifest.license === "string") return manifest.license;
  if (manifest.license?.type) return manifest.license.type;
  if (Array.isArray(manifest.licenses)) return manifest.licenses.map((l) => l.type ?? l).join(" OR ");
  return "UNKNOWN";
}

const seen = new Map();
const missing = [];
const queue = [join(frontend, "apps", "web")];
while (queue.length > 0) {
  const directory = queue.pop();
  const manifest = readManifest(directory);
  const id = `${manifest.name}@${manifest.version}`;
  if (seen.has(id)) continue;
  seen.set(id, {
    name: manifest.name,
    version: manifest.version,
    license: licenseOf(manifest),
    private: manifest.private === true,
    directory,
  });
  const dependencies = { ...manifest.dependencies, ...manifest.optionalDependencies };
  for (const name of Object.keys(dependencies)) {
    const resolved = resolvePackage(name, directory);
    if (resolved) queue.push(resolved);
    else if (!(name in (manifest.optionalDependencies ?? {}))) missing.push(`${name} (needed by ${id})`);
  }
}

const problems = missing.map((entry) => `not installed: ${entry}`);
const counts = { allowed: 0, weak: 0, ours: 0 };
for (const [id, { name, license, private: isPrivate }] of seen) {
  if (isPrivate || name.startsWith("@agnostic/")) {
    counts.ours += 1;
  } else if (name in WEAK_ALLOWED) {
    counts.weak += 1;
  } else if (FORBIDDEN.test(license) && !PERMISSIVE.test(license)) {
    problems.push(`${id}: forbidden license ${license}`);
  } else if (WEAK.test(license) && !PERMISSIVE.test(license)) {
    problems.push(`${id}: weak-copyleft ${license} has not been reviewed (add it to WEAK_ALLOWED)`);
  } else if (PERMISSIVE.test(license)) {
    counts.allowed += 1;
  } else {
    problems.push(`${id}: unknown license ${license}`);
  }
}

console.log(
  `frontend (shipped): ${counts.allowed} allowed, ${counts.weak} weak, ${counts.ours} workspace packages`,
);
for (const problem of problems) console.log(`  - ${problem}`);
process.exitCode = problems.length > 0 ? 1 : 0;

const LICENSE_FILE = /^(LICEN[CS]E|COPYING|NOTICE)(\.(md|txt))?$/i;

function licenseTexts(directory) {
  return readdirSync(directory)
    .filter((file) => LICENSE_FILE.test(file))
    .sort()
    .map((file) => readFileSync(join(directory, file), "utf8").trim());
}

const target = process.argv.indexOf("--write");
if (target !== -1 && problems.length === 0) {
  const output = process.argv[target + 1];
  const lines = [
    "# Third-party software (web app)",
    "",
    "Packages bundled into the web app, with the license each declares and the license files it ships.",
    "",
  ];
  const shipped = [...seen.values()]
    .filter((entry) => !entry.private && !entry.name.startsWith("@agnostic/"))
    .sort((a, b) => a.name.localeCompare(b.name));
  for (const entry of shipped) {
    lines.push(`## ${entry.name} ${entry.version}`, "", `License: ${entry.license}`);
    for (const text of licenseTexts(entry.directory)) lines.push("", "```text", text, "```");
    lines.push("");
  }
  writeFileSync(output, lines.join("\n"), "utf8");
  console.log(`wrote ${output}`);
}
