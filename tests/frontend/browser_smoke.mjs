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
  await page.waitForFunction(() => Boolean(document.querySelector('[data-view="commands"]')));

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
      hasCommandsNav: Boolean(document.querySelector('[data-view="commands"]')),
      welcomeOpen: Boolean(document.getElementById("welcomeDialog")?.open),
      fetchLooksPatched: String(window.fetch).includes("isQuick")
        || String(window.fetch).includes("quick-create"),
    };
  });

  if (contract.version !== "1.2.5a1") {
    throw new Error(`Unexpected Studio version: ${contract.version}`);
  }
  if (contract.publicHasApiKey) throw new Error("/api/config exposed api_key");
  if (contract.legacyScopeNodes.length) {
    throw new Error(`Legacy scope nodes returned: ${contract.legacyScopeNodes.join(", ")}`);
  }
  if (!contract.hasDestination) throw new Error("Quick Create Destination UI did not initialize");
  if (!contract.hasBulkTrash) throw new Error("Library bulk Trash control is missing");
  if (!contract.hasCommandsNav) throw new Error("Command Center navigation is missing");
  if (contract.fetchLooksPatched) throw new Error("Quick Create patched global window.fetch");
  if (contract.prepared.forced_kind !== "entity" || contract.prepared.entity_type !== "character") {
    throw new Error(`Quick Create payload contract failed: ${JSON.stringify(contract.prepared)}`);
  }

  if (contract.welcomeOpen) {
    await page.click("#welcomeSkipX");
    await page.waitForFunction(() => !document.getElementById("welcomeDialog")?.open);
  }

  await page.click("#settingsBtn");
  await page.waitForFunction(() => (
    document.getElementById("inspector")?.classList.contains("open")
    && document.querySelector('[data-inspector-panel="runtime"]')?.classList.contains("active")
  ));
  await page.click("#closeInspectorBtn");
  await page.waitForFunction(() => !document.getElementById("inspector")?.classList.contains("open"));

  await page.click('[data-view="commands"]');
  await page.waitForFunction(() => document.getElementById("commandCenterView")?.classList.contains("active"));
  const commandCenterText = await page.locator("#commandCenterView").innerText();
  if (!commandCenterText.includes("Command Center")) throw new Error("Command Center did not render");
  if (!commandCenterText.includes("Built-in")) throw new Error("Built-in command docs tab is missing");
  if (!commandCenterText.includes("Custom")) throw new Error("Custom commands tab is missing");
  if (!commandCenterText.includes("References")) throw new Error("Reference guide tab is missing");

  await page.click("#newChatBtn");
  await page.waitForFunction(() => document.getElementById("chatView")?.classList.contains("active"));
  await page.waitForFunction(() => window.ArlineRuntime?.getState?.().commandRegistryVersion === "1.2.4a1");
  if (!(await page.locator("#deliberationOutput").count())) throw new Error("Intuition inspector panel is missing");
  await page.waitForFunction(() => Boolean(window.ArlineChatViewport?.initialized && window.ArlineMessageRuntime));
  await page.waitForFunction(() => document.querySelector("#composerDock .composer-card")?.classList.contains("composer-chatgpt-shell"));

  const composerContract = await page.evaluate(() => ({
    placeholder: document.getElementById("promptInput")?.placeholder,
    chrome: document.querySelector("#composerDock .composer-card")?.dataset.composerChrome,
    profileInActions: Boolean(document.querySelector("#composerDock .composer-actions #composerProfileBtn")),
    contextOnLeft: Boolean(document.querySelector("#composerDock .composer-profile-controls #analyzeBtn")),
    runProfileInPopover: Boolean(document.querySelector("#composerAdvanced #runProfileSelect")),
    modelInPopover: Boolean(document.querySelector("#composerAdvanced #modelSelect")),
    reasoningInPopover: Boolean(document.querySelector("#composerAdvanced #reasoningSelect")),
    hidden: document.getElementById("composerAdvanced")?.classList.contains("hidden"),
  }));
  if (composerContract.placeholder !== "Message Arline…") throw new Error(`Composer placeholder mismatch: ${JSON.stringify(composerContract)}`);
  if (composerContract.chrome !== "chatgpt-v1") throw new Error(`Composer chrome did not initialize: ${JSON.stringify(composerContract)}`);
  if (!composerContract.profileInActions || !composerContract.contextOnLeft) throw new Error(`Composer actions were not reorganized: ${JSON.stringify(composerContract)}`);
  if (!composerContract.runProfileInPopover || !composerContract.modelInPopover || !composerContract.reasoningInPopover) {
    throw new Error(`Composer settings were not moved into the popover: ${JSON.stringify(composerContract)}`);
  }
  if (!composerContract.hidden) throw new Error(`Composer settings should start closed: ${JSON.stringify(composerContract)}`);

  await page.click("#composerProfileBtn");
  await page.waitForFunction(() => !document.getElementById("composerAdvanced")?.classList.contains("hidden"));
  const composerPopoverText = await page.locator("#composerAdvanced").innerText();
  for (const label of ["Generation", "Model", "Effort", "Run profile", "Advanced"]) {
    if (!composerPopoverText.includes(label)) throw new Error(`Composer popover missing ${label}: ${composerPopoverText}`);
  }
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.getElementById("composerAdvanced")?.classList.contains("hidden"));

  const scrollContract = await page.evaluate(async () => {
    const controller = window.ArlineChatViewport;
    const feed = document.getElementById("conversationFeed");
    const section = document.getElementById("conversationSection");
    const landing = document.getElementById("chatLanding");
    const wasLandingHidden = landing.classList.contains("hidden");
    const wasSectionHidden = section.classList.contains("hidden");
    landing.classList.add("hidden");
    section.classList.remove("hidden");
    const token = controller.beginSession("SCROLL-SMOKE");
    feed.innerHTML = Array.from({ length: 24 }, (_, index) => (
      `<article class="turn" data-turn-id="SMOKE-${index}" data-message-id="SMOKE-${index}" style="min-height:140px"><div class="turn-assistant">smoke ${index}</div></article>`
    )).join("");
    await controller.finishSessionRender(token, { defaultToBottom: true });
    controller.renderRail();

    // ResizeObserver and scrollToLatest intentionally finish over animation
    // frames. Exercise a real user scroll only after those render callbacks have
    // had a chance to settle, then keep asserting that the controller reaches
    // READING rather than papering over the state transition.
    const nextFrame = () => new Promise((resolve) => requestAnimationFrame(resolve));
    await nextFrame();
    await nextFrame();
    const viewport = document.getElementById("chatViewport");
    const targetTop = () => Math.max(0, viewport.scrollHeight - viewport.clientHeight - 620);
    for (let attempt = 0; attempt < 12 && controller.debugState().mode !== "reading"; attempt += 1) {
      viewport.dispatchEvent(new WheelEvent("wheel", { deltaY: -500, bubbles: true }));
      viewport.scrollTop = targetTop();
      viewport.dispatchEvent(new Event("scroll"));
      await nextFrame();
      await nextFrame();
    }
    const before = controller.captureAnchor();
    const readingMode = controller.debugState().mode;
    const streamBefore = viewport.scrollTop;
    const live = window.createLiveTurn({ prompt: "streaming smoke", model: "fixture" });
    const liveOutput = live.node.querySelector(".live-output");
    for (let index = 0; index < 8; index += 1) {
      live.answer += ` token-${index}`;
      liveOutput.textContent = live.answer;
      live.node.scrollIntoView({ block: "end" });
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    const streamDrift = Math.abs(viewport.scrollTop - streamBefore);
    live.node.remove();
    const removal = feed.querySelector('[data-message-id="SMOKE-1"]');
    await controller.withMutation(() => removal?.remove(), { reason: "browser-smoke-delete" });
    const after = controller.captureAnchor(before?.anchorMessageId);
    const drift = before && after ? Math.abs(Number(after.offset) - Number(before.offset)) : 999;
    const railMarkers = document.querySelectorAll("#chatScrollRail .chat-scroll-marker").length;
    const jumpVisible = !document.getElementById("jumpToLatestBtn").classList.contains("hidden");
    feed.innerHTML = "";
    if (!wasLandingHidden) landing.classList.remove("hidden");
    if (wasSectionHidden) section.classList.add("hidden");
    controller.beginSession(null);
    return { readingMode, streamDrift, drift, railMarkers, jumpVisible, state: controller.debugState() };
  });
  if (scrollContract.readingMode !== "reading") throw new Error(`Scroll controller did not enter reading mode: ${JSON.stringify(scrollContract)}`);
  if (scrollContract.streamDrift > 2) throw new Error(`Streaming stole the reading position: ${JSON.stringify(scrollContract)}`);
  if (scrollContract.drift > 2) throw new Error(`Anchor drifted during mutation: ${JSON.stringify(scrollContract)}`);
  if (scrollContract.railMarkers < 20) throw new Error(`Scroll rail markers missing: ${JSON.stringify(scrollContract)}`);
  if (!scrollContract.jumpVisible) throw new Error(`Jump-to-latest did not appear in reading mode: ${JSON.stringify(scrollContract)}`);

  await page.fill("#promptInput", "/intu");
  await page.waitForFunction(() => !document.getElementById("slashPopup")?.classList.contains("hidden"));
  if (!(await page.locator("#slashPopup").innerText()).includes("/intuition")) throw new Error("/intuition is missing from slash discovery");
  await page.fill("#promptInput", "@po");
  await page.waitForFunction(() => !document.getElementById("mentionPopup")?.classList.contains("hidden"));
  if (!(await page.locator("#mentionPopup").innerText()).includes("pov")) throw new Error("@pov is missing from dynamic reference discovery");
  await page.fill("#promptInput", "");

  if (pageErrors.length) throw new Error(`Page errors:\n${pageErrors.join("\n")}`);
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
