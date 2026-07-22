/**
 * rvs-demo-npm — fetches npm package metadata from the public registry.
 *
 * Usage:
 *   node src/index.js info lodash
 *   node src/index.js versions axios --limit 5
 */

import axios from "axios";
import chalk from "chalk";
import { z } from "zod";
import { formatPackageInfo, formatVersionList } from "./utils.js";

const PackageInfo = z.object({
  name: z.string(),
  version: z.string(),
  description: z.string().optional(),
  homepage: z.string().optional(),
  license: z.string().optional(),
  author: z.union([z.string(), z.object({ name: z.string() })]).optional(),
  repository: z.object({ url: z.string() }).optional(),
});

async function fetchPackageInfo(name) {
  const resp = await axios.get(`https://registry.npmjs.org/${encodeURIComponent(name)}/latest`);
  return PackageInfo.parse(resp.data);
}

async function fetchVersions(name, limit = 10) {
  const resp = await axios.get(`https://registry.npmjs.org/${encodeURIComponent(name)}`);
  const versions = Object.keys(resp.data.versions ?? {});
  // Return newest first
  return versions.slice(-limit).reverse();
}

const [, , cmd, name, ...flags] = process.argv;

if (!cmd || !name) {
  console.log(chalk.bold("Usage:"));
  console.log("  node src/index.js info <package>");
  console.log("  node src/index.js versions <package> [--limit N]");
  process.exit(0);
}

const limitIdx = flags.indexOf("--limit");
const limit = limitIdx !== -1 ? parseInt(flags[limitIdx + 1] ?? "10", 10) : 10;

try {
  if (cmd === "info") {
    const info = await fetchPackageInfo(name);
    console.log(formatPackageInfo(info));
  } else if (cmd === "versions") {
    const vers = await fetchVersions(name, limit);
    console.log(formatVersionList(name, vers));
  } else {
    console.error(chalk.red(`Unknown command: ${cmd}`));
    process.exit(1);
  }
} catch (err) {
  console.error(chalk.red(`Error: ${err.message}`));
  process.exit(1);
}
