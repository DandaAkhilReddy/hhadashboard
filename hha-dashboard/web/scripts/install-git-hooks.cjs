#!/usr/bin/env node
/**
 * Install the repo-root .husky pre-commit hook.
 *
 * Runs from web/ via the `prepare` npm script. Cross-platform (Windows
 * cmd.exe + POSIX sh handle the same Node.js call). No-op outside a
 * git repo (CI cache restores can hit this).
 *
 * Audit ticket T3b.
 */
const { execSync } = require("node:child_process");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "../../..");

try {
  execSync("git config core.hooksPath .husky", {
    cwd: repoRoot,
    stdio: "ignore",
  });
} catch {
  // git config can fail in non-repo environments; safe to ignore.
}
