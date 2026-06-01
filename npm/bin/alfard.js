#!/usr/bin/env node
"use strict";

const { spawnSync, spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const PKG_VERSION = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8")
).version;

const IS_WINDOWS = process.platform === "win32";

function run(cmd, args, opts) {
  return spawnSync(cmd, args, { encoding: "utf8", ...opts });
}

// ── Step 1: check Python 3.11+ ────────────────────────────────────────────────

function getPython() {
  const candidates = IS_WINDOWS ? ["python", "python3"] : ["python3", "python"];
  for (const candidate of candidates) {
    const result = run(candidate, ["--version"], { stdio: "pipe" });
    if (result.status === 0) {
      const output = (result.stdout || result.stderr || "").trim();
      const match = output.match(/Python (\d+)\.(\d+)/);
      if (match) {
        const major = parseInt(match[1], 10);
        const minor = parseInt(match[2], 10);
        if (major > 3 || (major === 3 && minor >= 11)) {
          return candidate;
        }
      }
    }
  }
  return null;
}

const python = getPython();
if (!python) {
  console.error(
    "Alfard requires Python 3.11 or higher.\n" +
    "Download it from https://python.org and re-run this command."
  );
  process.exit(1);
}

// ── Step 2: ensure pipx ────────────────────────────────────────────────────────

function hasPipx() {
  return run("pipx", ["--version"], { stdio: "pipe" }).status === 0;
}

if (!hasPipx()) {
  console.log("pipx not found — installing automatically...");
  const pip = IS_WINDOWS ? "pip" : "pip3";
  const install = run(pip, ["install", "pipx", "--quiet"], { stdio: "inherit" });
  if (install.status !== 0) {
    // try the other pip
    const pip2 = IS_WINDOWS ? "pip3" : "pip";
    const install2 = run(pip2, ["install", "pipx", "--quiet"], { stdio: "inherit" });
    if (install2.status !== 0) {
      console.error(
        "Could not install pipx automatically.\n" +
        "Install it manually: pip install pipx\n" +
        "Then run: pipx install alfard"
      );
      process.exit(1);
    }
  }
  if (!hasPipx()) {
    console.error(
      "Could not install pipx automatically.\n" +
      "Install it manually: pip install pipx\n" +
      "Then run: pipx install alfard"
    );
    process.exit(1);
  }
}

// ── Step 3 & 4: install or upgrade alfard ─────────────────────────────────────

const alfardCmd = IS_WINDOWS ? "alfard.exe" : "alfard";

function getInstalledVersion() {
  const result = run(alfardCmd, ["--version"], { stdio: "pipe" });
  if (result.status !== 0) return null;
  const output = (result.stdout || result.stderr || "").trim();
  // expect output like "alfard 0.1.17" or "0.1.17"
  const match = output.match(/(\d+\.\d+\.\d+)/);
  return match ? match[1] : null;
}

const installedVersion = getInstalledVersion();

if (!installedVersion) {
  console.log("Installing alfard via pipx...");
  const install = spawnSync("pipx", ["install", "alfard"], { stdio: "inherit" });
  if (install.status !== 0) {
    process.exit(install.status ?? 1);
  }
} else if (installedVersion !== PKG_VERSION) {
  console.log(`Upgrading alfard from ${installedVersion} to ${PKG_VERSION}...`);
  const upgrade = spawnSync("pipx", ["upgrade", "alfard"], { stdio: "inherit" });
  if (upgrade.status !== 0) {
    process.exit(upgrade.status ?? 1);
  }
}

// ── Step 5: launch alfard ─────────────────────────────────────────────────────

const child = spawn(alfardCmd, process.argv.slice(2), { stdio: "inherit" });

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 0);
  }
});
