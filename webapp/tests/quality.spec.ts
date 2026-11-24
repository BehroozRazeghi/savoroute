import { expect, test } from '@playwright/test';

const status = { enabled: true, consent_required: true, limitations: 'Optional web search' };

test('nearby municipality choices are explicit, editable and sent with consent', async ({ page }) => {
  await page.route('**/v1/live/status', async route => route.fulfill({ json: status }));
  let calls = 0;
  await page.route('**/v1/live/discover', async route => {
    const input = route.request().postDataJSON();
    expect(input.geography_scope).toBe('nearby');
    expect(input.city).toBe('Boston');
    expect(input.nearby_cities).toEqual(['Cambridge', 'Somerville', 'Brookline']);
    expect(input.region).toBe('MA');
    expect(input.country).toBe('United States');
    expect(input.consent_remote_processing).toBe(true);
    calls++;
    await route.fulfill({ json: {
      provider: 'test', requested_cuisine: 'Persian', requested_city: 'Boston',
      geography_scope: 'nearby', requested_cities: ['Boston', 'Cambridge', 'Somerville', 'Brookline'],
      catalog_synthetic: false, catalog_results: [], linked_sources: [], web_results: [
        { name: 'Example (automated test)', city: 'Cambridge', region: 'MA', country: 'US',
          cuisine: 'Iranian', source_title: 'Mock search source', source_url: 'https://example.org/mock',
          source_label: 'web_search_source_not_independently_verified' },
      ], limitations: 'Source claims are not independently verified',
    } });
  });
  await page.goto('/app/');
  await page.getByLabel('Required cuisine').fill('Persian');
  await page.getByLabel('Required city').fill('Boston');
  await page.getByLabel('Geographic coverage').selectOption('nearby');
  await page.getByRole('button', { name: /Use suggested nearby Boston municipalities/ }).click();
  await page.getByLabel('Selected nearby cities (comma separated)').fill('Cambridge, Somerville, Brookline');
  await page.getByLabel(/I agree to send my search terms/).check();
  await page.getByRole('button', { name: 'Discover online' }).click();
  await expect(page.getByText('Example (automated test)')).toBeVisible();
  await expect(page.getByRole('heading', { name: /Results for Persian in Boston, Cambridge/ })).toBeVisible();
  expect(calls).toBe(1);
});

test('nearby scope requires jurisdiction before request', async ({ page }) => {
  await page.route('**/v1/live/status', async route => route.fulfill({ json: status }));
  await page.goto('/app/');
  await page.getByLabel('Required cuisine').fill('Persian');
  await page.getByLabel('Required city').fill('Boston');
  await page.getByLabel('Geographic coverage').selectOption('nearby');
  await page.getByLabel('Selected nearby cities (comma separated)').fill('Cambridge');
  await page.getByLabel(/I agree to send my search terms/).check();
  await expect(page.getByRole('button', { name: 'Discover online' })).toBeDisabled();
});
