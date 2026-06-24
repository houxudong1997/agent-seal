const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ 
    headless: true,
    executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  
  await page.goto('http://localhost:8081/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1500);
  
  await page.screenshot({
    path: 'F:\\workstation\\projects\\agent-seal\\screenshots\\after.png',
    fullPage: true
  });
  
  console.log('Screenshots saved successfully');
  await browser.close();
})();
