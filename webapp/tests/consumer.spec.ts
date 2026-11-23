import { test, expect } from '@playwright/test';

test('consumer app loads real catalog records and marks fictional data', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('pageerror', err => consoleErrors.push(err.message));
  await page.goto('/app/');
  await expect(page.getByRole('heading', { name: /Find your next good food decision/i })).toBeVisible();
  await expect(page.getByText('FICTIONAL DEMO')).toBeVisible();
  await expect(page.getByRole('article').first()).toBeVisible();
  await page.getByRole('button', { name: /View recorded details for/i }).first().click();
  await expect(page.getByRole('dialog', { name: 'Catalog entry details' })).toBeVisible();
  await page.getByRole('button', { name: 'Close details' }).click();
  expect(consoleErrors).toEqual([]);
});

test('search and recipe mode use existing API', async ({ page }) => {
  await page.goto('/app/');
  await page.getByRole('group', { name: 'Food type' }).getByRole('button', { name: 'Recipes' }).click();
  await expect(page.getByRole('heading', { name: 'Recipes to discover' })).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search food records' }).fill('noodles');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page.getByText(/search matches/)).toBeVisible();
});

test('mobile navigation is accessible without horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/app/');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();
  await page.getByRole('link', { name: 'Our approach' }).click();
  await expect(page.getByRole('button', { name: 'Open navigation' })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});

test('missing API data shows an honest error state', async ({ page }) => {
  await page.route('**/v1/**', route => route.fulfill({ status: 503, body: '{}' }));
  await page.goto('/app/');
  await expect(page.getByText('We couldn\'t load the records.')).toBeVisible();
});
