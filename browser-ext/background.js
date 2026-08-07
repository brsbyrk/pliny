const DEFAULT_SERVER_URL = "http://localhost:3131";

function getServerUrl() {
  return new Promise((resolve) => {
    chrome.storage.sync.get({ serverUrl: DEFAULT_SERVER_URL }, (items) => {
      resolve(items.serverUrl);
    });
  });
}

async function saveToPliny(url) {
  const serverUrl = await getServerUrl();
  const response = await fetch(`${serverUrl}/api/ingest/add-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  return await response.json();
}

// Create context menu items on install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "save-page",
    title: "Save this page to Pliny",
    contexts: ["page"],
  });
  chrome.contextMenus.create({
    id: "save-link",
    title: "Save this link to Pliny",
    contexts: ["link"],
  });
});

// Handle context menu clicks
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let url;
  if (info.menuItemId === "save-link" && info.linkUrl) {
    url = info.linkUrl;
  } else if (info.menuItemId === "save-page") {
    url = info.pageUrl;
  }

  if (!url) return;

  try {
    const result = await saveToPliny(url);
    if (result.status === "ingested") {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "Saved to Pliny",
        message: `✅ ${result.entry_id || "Saved"}`,
      });
    } else {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: "Save failed",
        message: `❌ ${result.error || "Unknown error"}`,
      });
    }
  } catch (err) {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: "Save failed",
      message: "❌ Server unreachable",
    });
  }
});

// Handle messages from popup.js
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "save") {
    saveToPliny(message.url)
      .then((result) => sendResponse({ success: true, data: result }))
      .catch((err) =>
        sendResponse({ success: false, error: "Server unreachable" })
      );
    return true; // Keep channel open for async response
  }
});
