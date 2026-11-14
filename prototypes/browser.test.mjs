// Optional: PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs CHROMIUM_EXECUTABLE=/path/to/chrome node prototypes/browser.test.mjs
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { freshModel } from './model.mjs';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.PREVIEW_URL || 'http://127.0.0.1:8765';
const screenshots = process.env.SCREENSHOT_DIR || '/tmp/opencode/wiipointer-designs';
await mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({ headless: true,
  ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}),
  args: ['--no-sandbox'],
});
const pages = ['home', 'pointer', 'buttons', 'lights', 'calibration', 'profiles', 'settings'];
let checks = 0;

async function navigate(page, theme, view) {
  await page.goto(`${base}/${theme}.html#${view}`);
  await page.waitForSelector(`main[data-page="${view}"]`);
}
async function setRange(page, id, value) {
  await page.locator(`#${id}`).evaluate((input, next) => {
    input.value = next; input.dispatchEvent(new Event('input', { bubbles: true }));
  }, String(value));
}
async function noOverflow(page, label) {
  const result = await page.evaluate(() => ({ width: innerWidth, content: document.documentElement.scrollWidth }));
  assert.ok(result.content <= result.width + 1, `${label}: horizontal overflow ${JSON.stringify(result)}`);
  assert.equal(await page.locator('main h1').count(), 1, `${label}: one page heading`);
  checks++;
}

try {
  for (const theme of ['original', 'neo']) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, reducedMotion: 'reduce' });
    const page = await context.newPage();
    const errors = [], external = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (!request.url().startsWith(base) && !request.url().startsWith('blob:')) external.push(request.url()); });

    await navigate(page, theme, 'home');
    await page.screenshot({ path: `${screenshots}/${theme}-home.png`, fullPage: true });
    for (const view of pages) { await navigate(page, theme, view); await noOverflow(page, `${theme}/${view}/desktop`); }

    await navigate(page, theme, 'pointer');
    await setRange(page, 'pointer-sensitivity', 18);
    assert.equal(await page.locator('[data-output="pointer.sensitivity"]').textContent(), '18 px/°');
    await page.locator('#pointer-linked').uncheck();
    await setRange(page, 'pointer-vertical', 9);
    await page.locator('#pointer-acceleration').uncheck();
    assert.equal(await page.locator('#pointer-strength').isDisabled(), true);
    await page.reload();
    assert.equal(await page.locator('#pointer-sensitivity').inputValue(), '18');
    assert.equal(await page.locator('#pointer-vertical').inputValue(), '9');
    await page.locator('#pointer-acceleration').check();
    const other = theme === 'original' ? 'neo' : 'original';
    await page.locator(`.design-switch a[href^="./${other}.html"]`).click();
    await page.waitForSelector('main[data-page="pointer"]');
    assert.equal(await page.locator('#pointer-sensitivity').inputValue(), '18');
    await page.locator(`.design-switch a[href^="./${theme}.html"]`).click();
    await page.waitForSelector('main[data-page="pointer"]');
    await page.locator('[data-grip="90"]').click();
    const pad = await page.locator('#aim-pad').boundingBox();
    await page.mouse.move(pad.x + 20, pad.y + 50);
    await page.mouse.move(pad.x + 130, pad.y + 80, { steps: 10 });
    assert.notEqual(await page.locator('#gain-value').textContent(), '1.00×');
    await page.locator('[data-action="target"]').click();
    assert.equal(await page.locator('#hit-count').textContent(), '1');
    await page.screenshot({ path: `${screenshots}/${theme}-pointer.png`, fullPage: true });

    await navigate(page, theme, 'buttons');
    await page.locator('svg [data-map-key="B"]').click();
    await page.locator('#map-1').selectOption('Right click');
    assert.ok((await page.locator('.inline-notice.warning').textContent()).includes('No hold-to-aim'));
    await page.locator('#map-1').selectOption('Keyboard shortcut');
    await page.locator('#shortcut-1').fill('Ctrl + Shift + P');
    assert.equal(await page.locator('#mapped-action').textContent(), 'Ctrl + Shift + P');
    await page.reload();
    assert.equal(await page.locator('#shortcut-1').inputValue(), 'Ctrl + Shift + P');
    await page.locator('[data-action="reset-buttons"]').click();
    assert.equal(await page.locator('#map-1').inputValue(), 'Hold to aim');
    await page.screenshot({ path: `${screenshots}/${theme}-buttons.png`, fullPage: true });

    await navigate(page, theme, 'lights');
    await page.locator('[data-pattern="custom"]').click();
    await page.locator('[data-light="1"]').click();
    await page.waitForFunction(() => document.querySelectorAll('.large-lights .is-on').length === 2);
    await page.locator('[data-pattern="wave"]').click();
    assert.equal(await page.locator('#lights-speed').isDisabled(), false);
    await page.screenshot({ path: `${screenshots}/${theme}-lights.png`, fullPage: true });

    await navigate(page, theme, 'profiles');
    await page.locator('[data-action="save-profile"]').click();
    await page.locator('#profile-name').fill('<b>Slides</b>');
    await page.locator('#profile-form button[type="submit"]').click();
    assert.equal(await page.locator('.profile-card h2').last().textContent(), '<b>Slides</b>');
    assert.equal(await page.locator('.profile-card h2 b').count(), 0, 'Profile names must be text, not markup');
    await navigate(page, theme, 'pointer');
    await setRange(page, 'pointer-sensitivity', 16);
    await navigate(page, theme, 'profiles');
    await page.locator('[data-action="update-profile"]').click();
    assert.equal(await page.locator('[data-action="update-profile"]').count(), 0);
    await page.locator('[data-delete-profile]').click();
    await page.locator('[data-confirm-delete]').click();
    assert.equal(await page.locator('.profile-card').count(), 3);

    await page.locator('#settings-file').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from('{"version":99}') });
    await page.waitForFunction(() => document.querySelector('#toast').textContent.startsWith('Could not import:'));
    await page.locator('#settings-file').setInputFiles({ name: 'good.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(freshModel())) });
    await page.waitForFunction(() => document.querySelector('#toast').textContent.startsWith('Preview settings imported'));
    const downloading = page.waitForEvent('download');
    await page.locator('[data-action="export"]').click();
    const download = await downloading;
    const exported = JSON.parse(await readFile(await download.path(), 'utf8'));
    assert.equal(exported.version, 1);
    assert.equal(exported.settings.pointer.sensitivity, 12);

    await navigate(page, theme, 'settings');
    await page.locator('#general-appearance').selectOption('Dark');
    if (theme === 'neo') assert.equal(await page.locator('html').getAttribute('data-appearance'), 'dark');
    await page.screenshot({ path: `${screenshots}/${theme}-settings.png`, fullPage: true });
    await page.locator('#general-appearance').selectOption('Light');
    await page.locator('#general-motion').selectOption('Reduced');
    assert.equal(await page.locator('html').getAttribute('data-motion'), 'reduced');
    await page.locator('[data-action="help"]').first().click();
    assert.equal(await page.locator('dialog').isVisible(), true);
    for (let i = 0; i < 6; i++) await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.querySelector('dialog').contains(document.activeElement)), true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog').isVisible(), false);

    await page.locator('#preview-state').selectOption('disconnected');
    await navigate(page, theme, 'home');
    assert.ok((await page.locator('main').textContent()).includes('Waiting for your remote'));
    await page.locator('#preview-state').selectOption('ready');

    for (const width of [1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 950 });
      for (const view of pages) { await navigate(page, theme, view); await noOverflow(page, `${theme}/${view}/${width}`); }
      if (width === 390) {
        await navigate(page, theme, 'home');
        await page.screenshot({ path: `${screenshots}/${theme}-mobile.png`, fullPage: true });
      }
    }
    await page.setViewportSize({ width: 390, height: 950 });
    await navigate(page, theme, 'settings');
    await page.locator('#general-textSize').selectOption('125');
    for (const view of pages) { await navigate(page, theme, view); await noOverflow(page, `${theme}/${view}/125%-text`); }

    // Virtual time exercises the complete countdown without making a real device wait.
    const calibration = await context.newPage();
    calibration.on('pageerror', error => errors.push(error.message));
    await calibration.clock.install();
    await navigate(calibration, theme, 'calibration');
    await calibration.locator('[data-action="start-calibration"]').click();
    assert.equal(await calibration.locator('.calibration-lights .is-on').count(), 4);
    await calibration.clock.runFor(1400);
    assert.equal(await calibration.locator('.calibration-lights .is-on').count(), 3);
    await calibration.clock.fastForward(4000);
    assert.ok((await calibration.locator('#cal-phase').textContent()).includes('MEASURING'));
    await calibration.locator('[data-action="wobble"]').click();
    await calibration.clock.fastForward(4000);
    assert.equal(await calibration.locator('[data-action="cancel-calibration"]').count(), 1);
    await calibration.clock.fastForward(1200);
    assert.equal(await calibration.locator('#cal-title').textContent(), 'All steady.');
    await calibration.locator('[data-action="start-calibration"]').click();
    await calibration.locator('[data-action="cancel-calibration"]').click();
    assert.equal(await calibration.locator('#cal-title').textContent(), 'Let’s find your steady.');
    await calibration.locator('[data-action="fail-calibration"]').click();
    assert.equal(await calibration.locator('#cal-title').textContent(), 'Not quite still enough.');
    assert.deepEqual(errors, [], `${theme}: browser errors`);
    assert.deepEqual(external, [], `${theme}: external network requests`);
    console.log(`${theme}: navigation, settings, mappings, lights, profiles, import/export, dialogs, states, calibration and responsive checks passed.`);
    await context.close();
  }
  const motionContext = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: 'no-preference' });
  const motionPage = await motionContext.newPage();
  const motionErrors = [];
  motionPage.on('pageerror', error => motionErrors.push(error.message));
  await navigate(motionPage, 'original', 'home');
  await motionPage.locator('.channel-grid a').first().focus();
  await motionPage.keyboard.press('ArrowRight');
  assert.equal(await motionPage.evaluate(() => document.activeElement.getAttribute('href')), '#buttons');
  await motionPage.keyboard.press('Enter');
  await motionPage.waitForSelector('main[data-page="buttons"]');
  await motionPage.locator('.skip-link').focus();
  await motionPage.keyboard.press('Enter');
  assert.equal(await motionPage.locator('main').getAttribute('data-page'), 'buttons');
  for (const view of ['pointer', 'lights', 'settings', 'home']) {
    await motionPage.evaluate(view => document.querySelector(`nav a[href="#${view}"]`).click(), view);
    await motionPage.waitForSelector(`main[data-page="${view}"]`);
  }
  assert.deepEqual(motionErrors, [], 'Keyboard navigation and interrupted full-motion transitions');
  await motionContext.close();
  console.log(`${checks} viewport/page layout checks passed. Screenshots: ${screenshots}`);
} finally {
  await browser.close();
}
