import chalk from "chalk";
import _ from "lodash";

/**
 * Format package info as a pretty table.
 * @param {object} info
 */
export function formatPackageInfo(info) {
  const author =
    typeof info.author === "object" ? info.author?.name : info.author;
  const repoUrl = info.repository?.url?.replace(/^git\+/, "").replace(/\.git$/, "");

  const pairs = _.omitBy(
    {
      Name: info.name,
      Version: info.version,
      Description: info.description,
      License: info.license,
      Author: author,
      Homepage: info.homepage,
      Repository: repoUrl,
    },
    (v) => !v
  );

  const lines = Object.entries(pairs).map(
    ([k, v]) => `  ${chalk.dim(_.padEnd(k, 14))} ${chalk.white(v)}`
  );

  return [
    chalk.bold.cyan(`\n  ${info.name} @ ${info.version}`),
    chalk.dim("  " + "─".repeat(50)),
    ...lines,
    "",
  ].join("\n");
}

/**
 * Format a list of versions.
 * @param {string} name
 * @param {string[]} versions
 */
export function formatVersionList(name, versions) {
  return [
    chalk.bold(`\n  ${name} — ${versions.length} versions`),
    ...versions.map((v) => `    ${chalk.cyan(v)}`),
    "",
  ].join("\n");
}
