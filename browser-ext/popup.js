const pageTitle = document.getElementById("page-title");
const pageUrl = document.getElementById("page-url");
const btnSave = document.getElementById("btn-save");
const status = document.getElementById("status");

// Get current tab info
chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
  const tab = tabs[0];
  if (tab) {
    pageTitle.textContent = tab.title || "(untitled)";
    pageUrl.textContent = tab.url || "";
  } else {
    pageTitle.textContent = "(no tab)";
    btnSave.disabled = true;
  }
});

// Save handler
btnSave.addEventListener("click", () => {
  const url = pageUrl.textContent;
  if (!url) return;

  btnSave.disabled = true;
  btnSave.textContent = "Saving...";
  status.className = "status";
  status.textContent = "";

  chrome.runtime.sendMessage({ action: "save", url }, (response) => {
    if (response && response.success) {
      const data = response.data;
      if (data.status === "ingested") {
        status.className = "status success";
        status.textContent = `✅ Saved: ${data.entry_id || "done"}`;
        setTimeout(() => window.close(), 2000);
      } else {
        status.className = "status error";
        status.textContent = `❌ ${data.error || "Unknown error"}`;
        btnSave.disabled = false;
        btnSave.textContent = "Save to Pliny";
      }
    } else {
      status.className = "status error";
      status.textContent = `❌ ${(response && response.error) || "Server unreachable"}`;
      btnSave.disabled = false;
      btnSave.textContent = "Save to Pliny";
    }
  });
});
