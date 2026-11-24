import { expect, test } from '@playwright/test';

const statusEnabled = { enabled: true, consent_required: true, limitations: 'External web search' };

test('live web search is off by default and local discovery remains usable', async ({ page }) => {
  await page.goto('/app/');
  await expect(page.getByText('Live web discovery is disabled on this server.')).toBeVisible();
  await expect(page.getByRole('article').first()).toBeVisible();
});

test('Persian cuisine and Boston city are explicit required constraints, not guessed', async ({ page }) => {
  await page.route('**/v1/live/status', async route => {
    await route.fulfill({ json: statusEnabled });
  });
  let calls = 0;
  await page.route('**/v1/live/discover', async route => {
    const body = route.request().postDataJSON();
    expect(body.cuisine).toBe('Persian');
    expect(body.city).toBe('Boston');
    expect(body.consent_remote_processing).toBe(true);
    calls += 1;
    await route.fulfill({ json: {
      provider: 'openai-web-search', requested_cuisine: 'Persian', requested_city: 'Boston',
      catalog_results: [],
      web_results: [{ name: 'Example Persian Restaurant', city: 'Boston', region: 'MA', country: '', cuisine: 'Iranian',
        source_url: 'https://example.org/persian', source_title: 'Restaurant directory',
        source_label: 'web_search_source_not_independently_verified' }],
      limitations: 'Not independently verified',
    } });
  });
  await page.goto('/app/');
  await page.getByLabel('Required cuisine').fill('Persian');
  await page.getByLabel('Required city').fill('Boston');
  await page.getByLabel('Additional request (optional)').fill('kebab');
  const submit = page.getByRole('button', { name: 'Discover online' });
  await expect(submit).toBeDisabled();
  await page.getByLabel(/I agree to send my search terms/).check();
  await submit.click();
  await expect(page.getByText('Example Persian Restaurant')).toBeVisible();
  const source = page.getByRole('link', { name: 'Source: Restaurant directory' });
  await expect(source).toHaveAttribute('href', 'https://example.org/persian');
  await expect(source).toHaveAttribute('rel', 'noopener noreferrer');
  expect(calls).toBe(1);
});

test('unsupported restaurant request returns no unrelated substitutes', async ({ page }) => {
  await page.route('**/v1/live/status', async route => { await route.fulfill({ json: statusEnabled }); });
  await page.route('**/v1/live/discover', async route => {
    await route.fulfill({ json: { provider: 'fake', requested_cuisine: 'Persian', requested_city: 'Boston',
      catalog_results: [], web_results: [], limitations: 'No verification' } });
  });
  await page.goto('/app/');
  await page.getByLabel('Required cuisine').fill('Persian');
  await page.getByLabel('Required city').fill('Boston');
  await page.getByLabel(/I agree to send my search terms/).check();
  await page.getByRole('button', { name: 'Discover online' }).click();
  await expect(page.getByText(/No source-supported matches found/)).toBeVisible();
  await expect(page.getByText(/We do not substitute unrelated restaurants/)).toBeVisible();
});

test('AI food interpretation can prefill an editable live discovery', async ({ page }) => {
  await page.route('**/v1/ai/status', async route => {
    await route.fulfill({ json: { enabled: true, input_types: ['text'], consent_required: true } });
  });
  await page.route('**/v1/live/status', async route => { await route.fulfill({ json: statusEnabled }); });
  await page.route('**/v1/ai/interpret', async route => {
    await route.fulfill({ json: { provider: 'mock', catalog_verified: false, limitations: '',
      interpretation: { search_query: 'Iranian restaurant', dishes: [], cuisines: ['Persian'],
        ingredients: [], uncertainties: [] } } });
  });
  await page.goto('/app/');
  await page.getByLabel('Describe your craving (optional with a photo)').fill('Persian food');
  await page.getByLabel(/I agree to send this description/).check();
  await page.getByRole('button', { name: 'Interpret food' }).click();
  await expect(page.getByLabel('Required cuisine (optional; exact catalog filter)')).toHaveValue('Persian');
  await page.getByRole('button', { name: 'Continue to live restaurant discovery' }).click();
  await expect(page.getByLabel('Required cuisine')).toHaveValue('Persian');
  await expect(page.getByLabel('Additional request (optional)')).toHaveValue('Iranian restaurant');
  await expect(page.getByLabel('Required city')).toHaveValue('');
});
