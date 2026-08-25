import { chromium } from "playwright";

const baseUrl = process.env.ARLINE_BROWSER_URL || "http://127.0.0.1:7860";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [];
const consoleErrors = [];
page.on("pageerror", (error) => pageErrors.push(String(error?.stack || error)));
page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });

try {
  const frontendStatus = await fetch(`${baseUrl}/api/frontend`).then((response) => response.json());
  if (frontendStatus.mode !== "react" || !frontendStatus.built) {
    throw new Error(`React frontend was not selected: ${JSON.stringify(frontendStatus)}`);
  }

  const response = await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30_000 });
  if (!response?.ok()) throw new Error(`Studio HTTP status ${response?.status()}`);
  await page.waitForSelector(".studio-shell", { state: "visible" });
  await page.waitForSelector(".studio-sidebar", { state: "visible" });

  const boot = await page.evaluate(() => ({
    hasLegacyRoot: Boolean(document.querySelector("#app.app-shell")),
    hasReactRoot: Boolean(document.querySelector("#root .studio-shell")),
    assetScripts: [...document.scripts].filter((script) => script.src.includes("/assets/")).length,
    title: document.title,
  }));
  if (boot.hasLegacyRoot) throw new Error("Legacy static app rendered instead of React");
  if (!boot.hasReactRoot) throw new Error("React root is missing");
  if (boot.assetScripts < 1) throw new Error("Vite asset bundle was not served");
  if (!boot.title.includes("Arline")) throw new Error(`Unexpected title: ${boot.title}`);

  await page.getByRole("button", { name: "Chat", exact: true }).click();
  await page.waitForSelector(".chat-workspace", { state: "visible" });
  await page.waitForSelector(".composer-shell textarea", { state: "visible" });
  const placeholder = await page.locator(".composer-shell textarea").getAttribute("placeholder");
  if (placeholder !== "Message Arline…") throw new Error(`Unexpected composer placeholder: ${placeholder}`);

  await page.locator(".global-command").click();
  await page.waitForSelector(".command-view", { state: "visible" });
  const commandHeading = page.getByRole("heading", { name: "Direct Arline explicitly", exact: true });
  if ((await commandHeading.count()) !== 1 || !(await commandHeading.isVisible())) {
    throw new Error("Command Center heading did not render");
  }

  await page.locator(".topbar-tools .icon-control").last().click();
  await page.waitForSelector(".settings-drawer", { state: "visible" });
  if (!(await page.locator(".settings-drawer").innerText()).toLowerCase().includes("models & runtime")) {
    throw new Error("Settings runtime panel is missing");
  }
  await page.locator(".settings-drawer > header .icon-control").click();
  await page.waitForSelector(".settings-drawer", { state: "detached" });

  await page.getByRole("button", { name: "Quick create", exact: true }).click();
  await page.waitForSelector(".quick-modal", { state: "visible" });
  if (!(await page.locator(".quick-modal").innerText()).toLowerCase().includes("describe it naturally")) {
    throw new Error("Quick Create did not render");
  }
  await page.locator(".quick-modal .modal-close").click();

  if (pageErrors.length) throw new Error(`Page errors:\n${pageErrors.join("\n")}`);
  const appConsoleErrors = consoleErrors.filter((line) => line.includes("TypeError") || line.includes("Uncaught") || line.includes("/assets/"));
  if (appConsoleErrors.length) throw new Error(`App console errors:\n${appConsoleErrors.join("\n")}`);

  console.log("Arline React browser smoke: ok", JSON.stringify(frontendStatus));
} finally {
  await browser.close();
}
