#!/usr/bin/env node
/**
 * resolve_reddit_share.js — Minimal Playwright script to resolve a
 * reddit.com/s/ share link to its canonical post URL.
 *
 * Share pages have a JS-based verification gate; Playwright handles it.
 * Once navigated, we read the final URL and extract the /comments/ path.
 *
 * Usage: node resolve_reddit_share.js <share-url>
 * Output: JSON { canonical_url: "..." } or { error: "..." }
 */
const { chromium } = require("playwright");

(async () => {
  const url = process.argv[2];
  if (!url) {
    console.log(JSON.stringify({ error: "No URL provided" }));
    process.exit(1);
  }

  let browser;
  try {
    browser = await chromium.launch({
      headless: true,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    });

    const context = await browser.newContext({
      userAgent:
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
      viewport: { width: 1280, height: 800 },
    });

    const page = await context.newPage();

    // Navigate to the share link; the page either redirects server-side
    // or shows a verification page that resolves via JS.
    await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });

    // Read the final URL after any JS-driven redirect
    const finalUrl = page.url();

    await browser.close();

    if (!finalUrl || finalUrl === url) {
      // Still on the share page — redirect may have failed
      console.log(JSON.stringify({ error: "No redirect occurred" }));
      process.exit(1);
    }

    // Extract the /comments/ portion, strip tracking parameters
    const canonical = finalUrl.split("?")[0];
    console.log(JSON.stringify({ canonical_url: canonical }));
  } catch (err) {
    if (browser) await browser.close().catch(() => {});
    console.log(JSON.stringify({ error: err.message }));
    process.exit(1);
  }
})();
