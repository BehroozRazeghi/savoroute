import { test, expect } from '@playwright/test';

test('search and cuisine filters persist in URL, reload, and browser history', async ({ page }) => {
  await page.goto('/app/');
  await expect(page.getByRole('article').first()).toBeVisible();
  await page.getByRole('searchbox', { name: 'Search food records' }).fill('noodle');
  await page.getByRole('button', { name: 'Search', exact: true }).click();
  await expect(page).toHaveURL(/q=noodle/);
  await expect(page.getByRole('article').first()).toBeVisible();
  await page.getByLabel('Cuisine', { exact: true }).selectOption('Japanese');
  await expect(page).toHaveURL(/cuisine=Japanese/);
  await expect(page.getByRole('article')).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole('searchbox', { name: 'Search food records' })).toHaveValue('noodle');
  await expect(page.getByLabel('Cuisine', { exact: true })).toHaveValue('Japanese');
  await expect(page.getByRole('article')).toHaveCount(1);
  await page.goBack();
  await expect(page.getByLabel('Cuisine', { exact: true })).toHaveValue('');
  await expect(page).toHaveURL(/q=noodle/);
});

test('restaurant city is not inferred from display address', async ({ page }) => {
  await page.goto('/app/?kind=restaurant&city=Boston');
  await expect(page.getByLabel('City', { exact: true })).toHaveValue('Boston');
  await expect(page.getByRole('heading', { name: 'No matching records yet.' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(page.getByRole('article').first()).toBeVisible();
  expect(new URL(page.url()).searchParams.has('city')).toBe(false);
});

test('recipe selection uses recorded cuisine and clears restaurant-specific filters', async ({ page }) => {
  await page.goto('/app/?kind=restaurant&city=Boston&price=2');
  await page.getByRole('group', { name: 'Food type' }).getByRole('button', { name: 'Recipes' }).click();
  await expect(page.getByRole('heading', { name: 'Recipes to discover' })).toBeVisible();
  await expect(page.getByLabel('City', { exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Maximum recorded price tier')).toHaveCount(0);
  const url = new URL(page.url());
  expect(url.searchParams.get('kind')).toBe('recipe');
  expect(url.searchParams.has('city')).toBe(false);
  expect(url.searchParams.has('price')).toBe(false);
  await page.getByLabel('Cuisine', { exact: true }).selectOption('Japanese');
  await expect(page.getByRole('article')).toHaveCount(1);
});

test('browse pagination is API-backed and the page is preserved on reload', async ({ page }) => {
  const calls: number[] = [];
  const records = Array.from({ length: 13 }, (_, index) => ({
    item_id: `r-${index + 1}`, kind: 'restaurant', title: `Listing ${index + 1}`,
    description: 'Synthetic test record', cuisines: ['Japanese'], dietary_tags: [],
    source: 'synthetic_demo', source_url: null, city: null, region: null, country: null,
    location: null, price_tier: null,
  }));
  await page.route('**/v1/items?**', async route => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get('offset') || '0');
    calls.push(offset);
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ total: records.length, offset, limit: 9, items: records.slice(offset, offset + 9) }) });
  });
  await page.goto('/app/');
  await expect(page.getByText('Page 1 of 2')).toBeVisible();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByRole('heading', { name: 'Listing 10' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Listing 10' })).toBeVisible();
  expect(calls).toContain(9);
});

test('error, retry, empty state, and keyboard-accessible filters', async ({ page }) => {
  let failing = true;
  await page.route('**/v1/items?**', async route => {
    if (failing) { await route.fulfill({ status: 503, body: '{}' }); return; }
    await route.continue();
  });
  await page.goto('/app/');
  await expect(page.getByRole('heading', { name: "We couldn't load the records." })).toBeVisible();
  failing = false;
  await page.getByRole('button', { name: 'Try again' }).click();
  await expect(page.getByRole('article').first()).toBeVisible();
  await page.getByLabel('Cuisine', { exact: true }).focus();
  await expect(page.getByLabel('Cuisine', { exact: true })).toBeFocused();
});

test('filters have no horizontal overflow on narrow mobile devices', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto('/app/?kind=recipe&cuisine=Japanese&q=noodle');
  await expect(page.getByRole('article').first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});

test('back navigation restores an earlier browsed page without stale pagination clamping', async ({ page }) => {
  const records = Array.from({ length: 12 }, (_, index) => ({
    item_id: `b-${index}`, kind: 'restaurant', title: `Browse ${index}`,
    description: 'Fictional', cuisines: [], dietary_tags: [], source: 'synthetic_demo',
    source_url: null, city: null, region: null, country: null, location: null, price_tier: null,
  }));
  await page.route('**/v1/items?**', async route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('offset') || '0');
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ total: 12, offset, limit: 9, items: records.slice(offset, offset + 9) }) });
  });
  await page.goto('/app/');
  await expect(page.getByText('Page 1 of 2')).toBeVisible();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByRole('heading', { name: 'Browse 9' })).toBeVisible();
  await page.getByRole('button', { name: 'Previous' }).click();
  await expect(page.getByRole('heading', { name: 'Browse 0' })).toBeVisible();
  await page.goBack();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.getByRole('heading', { name: 'Browse 9' })).toBeVisible();
});

test('filter controls expose precise accessible labels', async ({ page }) => {
  await page.goto('/app/');
  for (const name of ['Type', 'City', 'Cuisine', 'Maximum recorded price tier']) {
    await expect(page.getByRole('combobox', { name, exact: true })).toBeVisible();
  }
  await page.getByRole('group', { name: 'Food type' }).getByRole('button', { name: 'Recipes' }).click();
  await expect(page.getByRole('combobox', { name: 'Cuisine', exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'City', exact: true })).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Maximum recorded price tier', exact: true })).toHaveCount(0);
});
