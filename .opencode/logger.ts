/**
 * Engram — Plugin Logger
 * ========================
 *
 * Creates a logger function for selfExtract and other plugin operations.
 *
 * Writes structured logs to OpenCode's server-side log via client.app.log().
 * Shows TUI toasts for warnings via client.tui.showToast().
 *
 * Matches the (msg: string) => void signature expected by selfExtract.
 */

export function createPluginLogger(client: any): (msg: string) => void {
  function writeLog(level: "debug" | "info" | "warn" | "error", message: string) {
    try {
      client.app.log({ service: "engram", level, message })
    } catch {}
  }

  return (msg: string) => {
    const level = msg.includes("WARNING") ? "warn" : "info"
    writeLog(level, msg)
    if (level === "warn") {
      try {
        client.tui.showToast({
          body: { title: "Engram", message: msg, variant: "warning", duration: 15000 },
        }).catch(() => {})
      } catch {}
    }
  }
}
