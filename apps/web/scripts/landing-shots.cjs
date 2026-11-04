/* Regenerates the product screenshots on the landing page from a running local app.
 *
 *   HR_EMAIL=you@company.com HR_PASS='...' npm run landing:shots
 *
 * Set SHOTS_ONLY=product-dashboard to regenerate a single image.
 * Needs the web (3000) and API (8000) dev servers running and Google Chrome installed. Credentials
 * come from the environment only. The login email is masked and the Next.js dev badge hidden.
 * Run it during working hours (about 10:00-17:00 company time): the dashboard's "Present today"
 * reads 0 once the day's shifts have ended with open punches.
 */
const path = require("node:path");
const { chromium } = require("playwright");
const sharp = require("sharp");

const BASE = process.env.SHOTS_BASE_URL ?? "http://localhost:3000";
const OUT = path.join(__dirname, "..", "public", "landing");
const SHOTS = [
  // A narrower window than a real desktop, so the text stays legible once the image is scaled to
  // the page. Height is chosen to end the shot on content, with no empty space below it.
  { name: "product-dashboard", path: "/app/dashboard", viewport: { width: 1520, height: 950 } },
  { name: "product-employees", path: "/app/employees", viewport: { width: 1360, height: 850 }, hideRowsContaining: ["EMP-0001"] },
  { name: "product-payroll", path: "/app/payroll/pay-runs", viewport: { width: 1180, height: 520 } },
];

(async () => {
  const email = process.env.HR_EMAIL;
  const pass = process.env.HR_PASS;
  if (!email || !pass) throw new Error("Set HR_EMAIL and HR_PASS");
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH ?? "/usr/bin/google-chrome" });
  const page = await (await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1.5 })).newPage();
  await page.goto(`${BASE}/login`);
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', pass);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/app\//, { timeout: 60000 });

  for (const shot of SHOTS.filter((s) => !process.env.SHOTS_ONLY || s.name === process.env.SHOTS_ONLY)) {
    await page.setViewportSize(shot.viewport);
    await page.goto(BASE + shot.path, { waitUntil: "networkidle" });
    await page.addStyleTag({ content: "nextjs-portal,[data-nextjs-toast],[data-next-badge-root]{display:none!important}" });
    await page.evaluate(([em, hide]) => {
      const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (let n = w.nextNode(); n; n = w.nextNode()) {
        if (n.nodeValue.includes(em)) n.nodeValue = n.nodeValue.replace(em, "admin@yourcompany.com");
      }
      for (const row of document.querySelectorAll("tbody tr")) {
        if (hide.some((t) => row.textContent.includes(t))) row.remove();
      }
    }, [email, shot.hideRowsContaining ?? []]);
    await page.waitForTimeout(1200);
    const png = await page.screenshot();
    const info = await sharp(png).resize({ width: 1600 }).webp({ quality: 82 }).toFile(path.join(OUT, `${shot.name}.webp`));
    console.log(`${shot.name}.webp ${info.width}x${info.height}`);
  }
  await browser.close();
})();
