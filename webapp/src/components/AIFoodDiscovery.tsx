import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { ApiError, getAIStatus, interpretFood, type AIStatus, type FoodInterpretation } from '../lib/api';
import { Icon } from './Icon';

const MAX_UPLOAD_BYTES = 4_000_000;
const SUPPORTED = new Set(['image/png', 'image/jpeg', 'image/webp']);

async function preparePhoto(file: File): Promise<string> {
  if (!SUPPORTED.has(file.type)) throw new Error('Choose a JPEG, PNG, or WebP image.');
  if (file.size > MAX_UPLOAD_BYTES) throw new Error('Choose an image smaller than 4 MB.');
  // Browser-side re-encoding removes GPS/EXIF metadata before it leaves the device.
  const bitmap = await createImageBitmap(file);
  try {
    const scale = Math.min(1, 1536 / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('Image preparation is unavailable in this browser.');
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob(value => value ? resolve(value) : reject(new Error('Could not prepare image.')),
        'image/jpeg', 0.78));
    if (blob.size > MAX_UPLOAD_BYTES) throw new Error('Prepared image exceeds 4 MB.');
    const dataURL = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(new Error('Unable to read photo.'));
      reader.onload = () => resolve(String(reader.result));
      reader.readAsDataURL(blob);
    });
    const marker = 'base64,';
    const index = dataURL.indexOf(marker);
    if (index < 0) throw new Error('Unable to encode photo.');
    return dataURL.slice(index + marker.length);
  } finally {
    bitmap.close();
  }
}

type Props = {
  onUseSearch: (query: string, cuisine: string) => void;
  onDiscoverLive: (query: string, cuisine: string) => void;
};

export function AIFoodDiscovery({ onUseSearch, onDiscoverLive }: Props) {
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [prompt, setPrompt] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<FoodInterpretation | null>(null);
  const [suggestedQuery, setSuggestedQuery] = useState('');
  const [selectedCuisine, setSelectedCuisine] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const inFlight = useRef<AbortController | null>(null);
  const [preview, setPreview] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getAIStatus(controller.signal).then(setStatus).catch(() => {
      if (!controller.signal.aborted) setStatus({ enabled: false, input_types: [], consent_required: true });
    });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!file) { setPreview(null); return; }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => () => inFlight.current?.abort(), []);

  const choose = (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    event.target.value = '';
    setResult(null);
    setError('');
    if (chosen && (!SUPPORTED.has(chosen.type) || chosen.size > MAX_UPLOAD_BYTES)) {
      setFile(null);
      setError('Choose a JPEG, PNG, or WebP image smaller than 4 MB.');
    } else {
      setFile(chosen);
    }
  };

  const interpret = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || !status?.enabled || !consent) return;
    setError('');
    setResult(null);
    setBusy(true);
    const controller = new AbortController();
    inFlight.current = controller;
    try {
      const photo = file ? await preparePhoto(file) : null;
      if (controller.signal.aborted) return;
      const response = await interpretFood(prompt, photo, consent, controller.signal);
      if (!controller.signal.aborted) {
        setResult(response.interpretation);
        setSuggestedQuery(response.interpretation.search_query);
        setSelectedCuisine(response.interpretation.cuisines[0] ?? '');
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof ApiError ?
        failure.status === 429 ? 'AI usage limit reached. Try again later.' :
        failure.status === 413 ? 'The uploaded photo is too large.' :
        failure.status === 422 ? 'Check the description, consent and image format.' :
        failure.status === 503 ? 'AI interpretation is temporarily unavailable.' : failure.message :
        failure instanceof Error ? failure.message : 'Unable to interpret this input.');
    } finally {
      if (!controller.signal.aborted) { setBusy(false); setConsent(false); }
      if (inFlight.current === controller) inFlight.current = null;
    }
  };

  return <section className="ai-discovery" aria-labelledby="ai-title">
    <div className="ai-discovery-heading">
      <span className="eyebrow"><Icon name="leaf" size={15}/> OPTIONAL AI ASSISTANCE</span>
      <h2 id="ai-title">Discover food from a thought or photo.</h2>
      <p>AI suggests possible dishes and search words. Choose how to search: strict catalog filtering or separate, source-linked web discovery.</p>
    </div>
    {status === null ? <p role="status">Checking AI availability…</p> :
      !status.enabled ? <p className="ai-off" role="status">AI interpretation is not configured on this server. Regular food discovery is still available below.</p> :
        <form onSubmit={interpret} className="ai-form">
          <label htmlFor="ai-prompt">Describe your craving (optional with a photo)</label>
          <textarea id="ai-prompt" maxLength={500} rows={2} placeholder="For example: noodles with tofu and vegetables" value={prompt} disabled={busy}
            onChange={event => { setPrompt(event.target.value); setResult(null); }}/>
          <div className="ai-photo-actions">
            <label className="ai-photo-button">Choose a food photo
              <input aria-label="Choose food photo" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={choose}/>
            </label>
            <label className="ai-photo-button">Take a food photo
              <input aria-label="Take food photo" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" disabled={busy} onChange={choose}/>
            </label>
          </div>
          {file && <div className="ai-photo-preview">
            {preview && <img alt="Selected food photo, stored locally until submission" src={preview}/>}
            <span>{file.name} · {(file.size / 1024).toFixed(0)} KB</span>
            <button type="button" disabled={busy} onClick={() => { setFile(null); setResult(null); }}>Remove photo</button>
          </div>}
          <label className="ai-consent"><input type="checkbox" checked={consent} disabled={busy}
            onChange={event => setConsent(event.target.checked)}/>
            I agree to send this description and any selected photo to the configured external AI provider for interpretation.</label>
          <p className="ai-privacy">Photos are re-encoded to remove embedded metadata before transmission. AI guesses may be wrong; do not rely on them for allergies or dietary safety.</p>
          <button type="submit" className="ai-submit" disabled={busy || !consent || (!prompt.trim() && !file)}>
            {busy ? 'Interpreting…' : 'Interpret food'} <Icon name="arrow" size={15}/>
          </button>
          {error && <p role="alert" className="ai-error">{error}</p>}
          {result && <div className="ai-result" aria-live="polite">
            <strong>Possible food interpretation — review before searching</strong>
            {result.dishes.length > 0 && <p>Possible dishes: {result.dishes.join(', ')}</p>}
            {result.cuisines.length > 0 && <p>Possible cuisines: {result.cuisines.join(', ')}</p>}
            {result.uncertainties.length > 0 && <p>Uncertainties: {result.uncertainties.join('; ')}</p>}
            <label htmlFor="ai-suggested-query">Edit suggested search</label>
            <input id="ai-suggested-query" maxLength={180} value={suggestedQuery}
              onChange={event => setSuggestedQuery(event.target.value)}/>
            <label htmlFor="ai-selected-cuisine">Required cuisine (optional; exact catalog filter)</label>
            <select id="ai-selected-cuisine" value={selectedCuisine} onChange={event => setSelectedCuisine(event.target.value)}>
              <option value="">No required cuisine</option>
              {result.cuisines.map(value => <option value={value} key={value}>{value}</option>)}
            </select>
            <button type="button" className="ai-submit" disabled={!suggestedQuery.trim()}
              onClick={() => { onUseSearch(suggestedQuery.trim(), selectedCuisine); setResult(null); }}>Search catalog <Icon name="arrow" size={15}/></button>
            <button type="button" className="ai-photo-button" disabled={!suggestedQuery.trim() || !selectedCuisine}
              onClick={() => { onDiscoverLive(suggestedQuery.trim(), selectedCuisine); setResult(null); }}>
              Continue to live restaurant discovery
            </button>
          </div>}
        </form>}
  </section>;
}
