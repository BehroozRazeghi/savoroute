import { expect, test } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

// No live provider or secrets in browser CI: intercept only the opt-in AI routes.
test('AI is visibly unavailable by default and regular catalog search still works', async ({ page }) => {
  await page.goto('/app/');
  await expect(page.getByText('AI interpretation is not configured on this server.')).toBeVisible();
  await expect(page.getByRole('article').first()).toBeVisible();
});

test('interpretation requires consent and editable confirmation before catalog search', async ({ page }) => {
  let sent = 0;
  await page.route('**/v1/ai/status', async route => {
    await route.fulfill({ json: { enabled: true, input_types: ['text', 'image'], consent_required: true } });
  });
  await page.route('**/v1/ai/interpret', async route => {
    const data = route.request().postDataJSON();
    expect(data.consent_remote_processing).toBe(true);
    expect(data.prompt).toBe('spicy noodles');
    expect(data.image_base64).toBeNull();
    sent += 1;
    await route.fulfill({ json: {
      provider: 'openai', catalog_verified: false, limitations: 'Not verified',
      interpretation: { search_query: 'noodles', dishes: ['noodles'], cuisines: ['Japanese'],
        ingredients: [], uncertainties: ['Not certain'] },
    } });
  });
  await page.goto('/app/');
  await page.getByLabel('Describe your craving (optional with a photo)').fill('spicy noodles');
  const submit = page.getByRole('button', { name: 'Interpret food' });
  await expect(submit).toBeDisabled();
  await page.getByLabel(/I agree to send this description/).check();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByText('Possible dishes: noodles')).toBeVisible();
  await expect(page).not.toHaveURL(/q=noodles/);
  await page.getByLabel('Edit suggested search').fill('ramen');
  await page.getByRole('button', { name: 'Search catalog' }).click();
  await expect(page).toHaveURL(/q=ramen/);
  expect(sent).toBe(1);
});

test('food photo is transformed on-device before opt-in remote request', async ({ page }) => {
  await page.route('**/v1/ai/status', async route => {
    await route.fulfill({ json: { enabled: true, input_types: ['text', 'image'], consent_required: true } });
  });
  let captured = '';
  await page.route('**/v1/ai/interpret', async route => {
    const data = route.request().postDataJSON();
    captured = data.image_base64;
    expect(data.consent_remote_processing).toBe(true);
    expect(data.prompt).toBe('');
    await route.fulfill({ json: { provider: 'openai', catalog_verified: false, limitations: '',
      interpretation: { search_query: 'pasta', dishes: ['pasta'], cuisines: [],
        ingredients: [], uncertainties: [] },
    } });
  });
  await page.goto('/app/');
  const fixture = await readFile(resolve('..', 'data/sample/media/mushroom-pasta.png'));
  await page.getByLabel('Choose food photo').setInputFiles({
    name: 'photo.png', mimeType: 'image/png', buffer: fixture,
  });
  await page.getByLabel(/I agree to send this description/).check();
  await page.getByRole('button', { name: 'Interpret food' }).click();
  await expect(page.getByText('Possible dishes: pasta')).toBeVisible();
  // JPEG file magic 0xFFD8 (base64 /9j/) after client-side re-encoding.
  expect(captured.startsWith('/9j/')).toBe(true);
});
