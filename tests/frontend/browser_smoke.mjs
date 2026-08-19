import { chromium } from "playwright";

const baseUrl = process.env.ARLINE_BROWSER_URL || "http://127.0.0.1:7860";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [];
const consoleErrors = [];

page.on("pageerror", (error) => pageErrors.push(String(error?.stack || error)));
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});

try {
  const response = await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30_000 });
  if (!response?.ok()) throw new Error(`Studio HTTP status ${response?.status()}`);

  await page.waitForSelector("#brandBtn", { state: "visible" });
  await page.waitForFunction(() => (
    typeof window.ArlineStream?.consume === "function"
    && typeof window.ArlineRuntime?.getScope === "function"
    && typeof window.ArlineQuickCreate?.preparePayload === "function"
    && typeof window.ArlineQuickCreate?.previewOverride === "function"
  ));

  const contract = await page.evaluate(async () => {
    const publicConfig = await fetch("/api/config").then((res) => res.json());
    const prepared = window.ArlineQuickCreate.preparePayload({
      text: "Browser smoke character",
      forced_kind: "entity:character",
    });
    return {
      version: publicConfig.studio_version,
      publicHasApiKey: Object.prototype.hasOwnProperty.call(publicConfig, "api_key"),
      runtimeScope: window.ArlineRuntime.getScope(),
      prepared,
      legacyScopeNodes: ["projectSelect", "worldSelect", "branchSelect"]
        .filter((id) => document.getElementById(id)),
      hasDestination: Boolean(document.getElementById("quickCreateDestination")),
      hasBulkTrash: Boolean(document.getElementById("bulkTrashBtn")),
      welcomeOpen: Boolean(document.getElementById("welcomeDialog")?.open),
      fetchLooksPatched: String(window.fetch).includes("isQuick")
        || String(window.fetch).includes("quick-create"),
    };
  });

  if (contract.version !== "1.2.2a1") {
    throw new Error(`Unexpected Studio version: ${contract.version}`);
  }
  if (contract.publicHasApiKey) throw new Error("/api/config exposed api_key");
  if (contract.legacyScopeNodes.length) {
    throw new Error(`Legacy scope nodes returned: ${contract.legacyScopeNodes.join(", ")}`);
  }
  if (!contract.hasDestination) throw new Error("Quick Create Destination UI did not initialize");
  if (!contract.hasBulkTrash) throw new Error("Library bulk Trash control is missing");
  if (contract.fetchLooksPatched) throw new Error("Quick Create patched global window.fetch");
  if (contract.prepared.forced_kind !== "entity" || contract.prepared.entity_type !== "character") {
    throw new Error(`Quick Create payload contract failed: ${JSON.stringify(contract.prepared)}`);
  }

  // First-run onboarding is intentionally modal. Exercise the real dismiss
  // control before checking navigation so the smoke follows a user's path.
  if (contract.welcomeOpen) {
    await page.click("#welcomeSkipX");
    await page.waitForFunction(() => !document.getElementById("welcomeDialog")?.open);
  }

  // Settings is an inspector drawer rather than a workspace view. Exercise the
  // real open/close controls before moving on to normal workspace navigation.
  await page.click("#settingsBtn");
  await page.waitForFunction(() => (
    document.getElementById("inspector")?.classList.contains("open")
    && document.querySelector('[data-inspector-panel="runtime"]')?.classList.contains("active")
  ));
  await page.click("#closeInspectorBtn");
  await page.waitForFunction(() => !document.getElementById("inspector")?.classList.contains("open"));

  await page.click("#newChatBtn");
  await page.waitForFunction(() => document.getElementById("chatView")?.classList.contains("active"));

  if (pageErrors.length) throw new Error(`Page errors:\n${pageErrors.join("\n")}`);
  // Browser/network extensions occasionally emit console errors unrelated to the
  // app; keep only errors that clearly reference Arline source or uncaught JS.
  const appConsoleErrors = consoleErrors.filter((line) => (
    line.includes("/static/") || line.includes("Uncaught") || line.includes("TypeError")
  ));
  if (appConsoleErrors.length) {
    throw new Error(`App console errors:\n${appConsoleErrors.join("\n")}`);
  }

  console.log("Arline browser smoke: ok", JSON.stringify({
    version: contract.version,
    projectId: contract.runtimeScope.projectId,
    worldId: contract.runtimeScope.worldId,
  }));
} finally {
  await browser.close();
}
