import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp } from 'node:fs/promises';
import { dirname, join } from 'node:path';

const artifactPrefix = process.env.HIVE_SMOKE_ARTIFACT_PREFIX ?? 'work/hive-smoke-';
await mkdir(dirname(artifactPrefix), { recursive: true });
const artifacts = await mkdtemp(artifactPrefix);
console.log(`Browser artifacts: ${artifacts}`);
const origin = new URL(process.env.HIVE_SMOKE_URL ?? 'http://127.0.0.1:5173').origin;

const browser = await chromium.launch({
  channel: process.env.HIVE_BROWSER_CHANNEL ?? 'msedge',
  headless: true,
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  const response = await page.goto(`${origin}/app/agents`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  assert.equal(response.status(), 200);
  assert.match(await page.title(), /HIVE/);
  const real = process.env.HIVE_BROWSER_REAL_MODELS === '1';
  await page.getByText(real ? 'Ollama Online' : 'Ollama Offline', { exact: true }).first().waitFor();
  const runButton = page.locator('.review-run-btn').first();
  const runResponse = page.waitForResponse(
    response => response.url().endsWith('/api/v1/agent-runs') && response.request().method() === 'POST',
  );
  await runButton.click();
  const run = await (await runResponse).json();
  assert.equal(run.status, 'FAILED');
  assert.match(run.error_message, /market quote|Ollama is disabled/);
  await page.getByText(/Run failed.*Review: ERROR/).waitFor();
  await page.screenshot({ path: join(artifacts, 'agent-center-unavailable.png'), fullPage: true });
  if (real) {
    await page.getByLabel('Cutoff date (end of day UTC)').fill('2026-10-16');
    const research = page.waitForResponse(
      response => response.url().endsWith('/api/v1/agent-runs') && response.request().method() === 'POST',
      { timeout: 250000 },
    );
    await page.getByRole('button', { name: 'Replay RELIANCE at Cutoff' }).click();
    const completed = await (await research).json();
    assert.equal(completed.status, 'COMPLETED', completed.error_message);
    assert.equal(completed.executor_model, 'qwen3.5:4b');
    assert.equal(completed.reviewer_model, 'hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M');
    await page.getByText(new RegExp(`Agent run ${completed.run_id}.*COMPLETED`)).waitFor();
    await page.screenshot({ path: join(artifacts, 'historical-research.png'), fullPage: true });
    console.log(JSON.stringify({ live_run_id: completed.run_id, review_verdict: completed.review_verdict }));
  }
  const portfolioBefore = await (await page.request.get(`${origin}/api/v1/portfolio`)).json();
  const datasetLoad = page.waitForResponse(response => response.url().endsWith('/api/v1/datasets'));
  await page.goto(`${origin}/app/backtest`, { waitUntil: 'domcontentloaded' });
  const datasets = await (await datasetLoad).json();
  assert.ok(datasets.length > 0);
  const backtest = page.waitForResponse(
    response => response.url().endsWith('/api/v1/backtests') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Run Backtest' }).click();
  const backtestResponse = await backtest;
  assert.equal(backtestResponse.status(), 200, await backtestResponse.text());
  const result = await backtestResponse.json();
  assert.equal(result.data_source, 'historical');
  assert.ok(result.equity_curve.length > 0);
  await page.getByText('Net after fees', { exact: true }).waitFor();
  await page.getByText('Buy & Hold Benchmark', { exact: true }).waitFor();
  await page.locator('path.recharts-line-curve').waitFor();
  await page.screenshot({ path: join(artifacts, 'backtest.png'), fullPage: true });
  const portfolioAfter = await (await page.request.get(`${origin}/api/v1/portfolio`)).json();
  assert.equal(portfolioAfter.cash, portfolioBefore.cash);
  assert.deepEqual(portfolioAfter.positions, portfolioBefore.positions);
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ backtest_id: result.run_id, observations: result.equity_curve.length, trades: result.trade_count, portfolio_cash: portfolioAfter.cash }));
  console.log(JSON.stringify({ title: await page.title(), run_id: run.run_id, persisted_status: run.status, error_message: run.error_message }));
} finally {
  await browser.close();
}
