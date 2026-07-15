/**
 * Detects whether the plugin runs from npm (root includes "node_modules") or local dev.
 * The config hook uses this to decide whether selfExtract() should fire.
 */

export type InstallType = "npm" | "local"

export interface InstallInfo {
  type: InstallType
  root: string
  isNpm: boolean
  isLocal: boolean
}

export function detectInstallType(root: string): InstallInfo {
  const isNpm = root.includes("node_modules")
  const isLocal = !isNpm
  const type: InstallType = isNpm ? "npm" : "local"
  return { type, root, isNpm, isLocal }
}
