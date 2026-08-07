const input = document.getElementById("server-url");
const btnSave = document.getElementById("btn-save-options");
const status = document.getElementById("status");

// Load current value
chrome.storage.sync.get({ serverUrl: "http://192.168.1.105:3131" }, (items) => {
  input.value = items.serverUrl;
});

// Save
btnSave.addEventListener("click", () => {
  const url = input.value.trim();
  if (!url) {
    status.className = "status error";
    status.textContent = "❌ URL cannot be empty";
    return;
  }
  chrome.storage.sync.set({ serverUrl: url }, () => {
    status.className = "status success";
    status.textContent = "✅ Saved";
    setTimeout(() => { status.textContent = ""; }, 2000);
  });
});
