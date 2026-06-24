const { chromium } = require('playwright');
const path = require('path');

const DASHBOARD_URL = 'http://127.0.0.1:8081';
const SCREENSHOTS_DIR = 'F:\\workstation\\projects\\agent-seal\\screenshots';

(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: 'chrome'
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: 'dark'
  });
  const page = await context.newPage();

  // ═══════════════════════════════════════════════════════
  // Screenshot 1: Main Dashboard — Live Events (full overview)
  // ═══════════════════════════════════════════════════════
  console.log('📸 Screenshot 1: Main Dashboard (Live Events tab)...');
  await page.goto(DASHBOARD_URL, { waitUntil: 'load', timeout: 30000 });
  await page.waitForTimeout(2000);

  // Click on first event row to expand its detail panel
  const rows = page.locator('table tbody tr');
  const rowCount = await rows.count();
  console.log(`  Found ${rowCount} event rows`);

  if (rowCount > 0) {
    await rows.nth(0).click();
    await page.waitForTimeout(500);
  }

  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, '01-main-dashboard.png'),
    fullPage: false
  });
  console.log('  ✅ Saved: 01-main-dashboard.png');

  // ═══════════════════════════════════════════════════════
  // Screenshot 2: Event Detail expanded (all panels open)
  // ═══════════════════════════════════════════════════════
  console.log('📸 Screenshot 2: Event Detail expanded...');

  // Expand all collapsible panels (OUTPUT, METADATA, FULL EVENT JSON)
  const panels = page.locator('button:has-text("OUTPUT"), button:has-text("METADATA"), button:has-text("FULL EVENT JSON")');
  const panelCount = await panels.count();
  console.log(`  Found ${panelCount} collapsible panels`);

  for (let i = 0; i < panelCount; i++) {
    const btn = panels.nth(i);
    const text = await btn.textContent();
    if (text && text.trim().startsWith('▶')) {
      await btn.click();
      await page.waitForTimeout(300);
    }
  }

  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, '02-event-detail.png'),
    fullPage: false
  });
  console.log('  ✅ Saved: 02-event-detail.png');

  // ═══════════════════════════════════════════════════════
  // Screenshot 3: Sessions Tab
  // ═══════════════════════════════════════════════════════
  console.log('📸 Screenshot 3: Sessions tab...');
  await page.locator('[role="tab"]:has-text("Sessions")').first().click();
  await page.waitForTimeout(1000);

  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, '03-sessions-list.png'),
    fullPage: false
  });
  console.log('  ✅ Saved: 03-sessions-list.png');

  // ═══════════════════════════════════════════════════════
  // Screenshot 4: Compliance Tab
  // ═══════════════════════════════════════════════════════
  console.log('📸 Screenshot 4: Compliance tab...');
  await page.locator('[role="tab"]:has-text("Compliance")').first().click();
  await page.waitForTimeout(1000);

  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, '04-compliance-view.png'),
    fullPage: false
  });
  console.log('  ✅ Saved: 04-compliance-view.png');

  await browser.close();
  console.log('🎉 All 4 screenshots captured successfully!');
})();
