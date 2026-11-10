# Text ingestion

Savoroute imports local text records into catalog schema v1. Source and extraction validation are separate from catalog admission.

## Input contract

`data/sample/ingestion_sources.json` is a fictional example. A source batch contains `source_schema_version: 1`, a dataset name and `synthetic` flag, and a nonempty `documents` array. Each document contains:

| Field | Meaning |
| --- | --- |
| `source_id` | Stable identifier supplied by the dataset producer; unique across imports into the same catalog |
| `kind` | `restaurant` or `recipe` |
| `source_name` | Name of the submitting source or dataset |
| `collected_at` | ISO 8601 timestamp with a UTC offset |
| `text` | UTF-8 text (maximum 16,000 normalized characters) |
| `source_url` | Optional HTTP(S) source reference; not fetched or verified |

Text is normalized to Unicode NFC, LF newlines, and stripped outer whitespace. The SHA-256 hash in the provenance file is computed over this normalized text, not the original file bytes. For reproducible evidence offsets, the source document remains available in the original input batch.

## Extraction

Two extraction paths share the same validator:

- `labeled`: parses one-line `Title:`, `Description:`, `Cuisines:`, `Dietary tags:`, `Ingredients:`, `Location:`, and `Price tier:` fields. This deterministic parser is limited to explicitly labeled input.
- `openai` or `ollama`: supplies free-form text to a text-generation model and validates its JSON response. Neither adapter has been exercised against a live provider in automated tests; adapter behavior is tested using local stand-ins.

Each extracted scalar or array element requires `value` and `quote`. The validator verifies that the quote is a literal substring of the normalized source and that the extracted value occurs inside that quote. It records the quote's half-open `[start, end)` character offsets. Duplicate list values, unsupported fields, missing required text, invalid types, and unsupported pricing are rejected. Restaurant entries require a quoted location; recipe entries cannot have location or price tier.

**These checks establish text attribution, not factual accuracy.** A quoted claim such as `vegan` remains a claim in the source. This system does not certify ingredients, allergies, dietary suitability, addresses, or restaurant availability. Existing catalog records are retained; an item is admitted only after its complete extraction validates.

`item_id` is derived from the SHA-256 hash of `source_id`. Source IDs must be stable and unique within the target catalog. Reimporting the same source into a catalog containing its item ID fails rather than overwriting an existing record. No deduplication of equivalent entities with different source IDs is performed.

## CLI

```bash
savoroute ingest \
  --sources data/sample/ingestion_sources.json \
  --output data/generated/catalog.json \
  --provenance data/generated/evidence.json

savoroute validate --catalog data/generated/catalog.json
savoroute search "ginger mushrooms" --catalog data/generated/catalog.json
```

The default base is the bundled 12-item fictional catalog. Use `--new-catalog` to create a catalog containing only the imported items; the new catalog inherits the source batch dataset name and synthetic flag. Use `--catalog <path>` for another existing catalog. Synthetic and non-synthetic datasets cannot be mixed.

The CLI rejects existing output files unless `--overwrite` is set. Each output file is written through a temporary file and replaced after serialization. The provenance file includes a SHA-256 digest of the exact serialized catalog file for pairing and integrity checks. The two outputs are **not a single atomic transaction**; for durable pipelines, manage them as a versioned pair.

Model-backed extraction, where enabled, transmits source text to the configured model endpoint. The CLI does not execute model calls by default.

### OpenAI

```bash
python -m pip install -e ".[openai]"
export OPENAI_API_KEY="..."  # supply in your shell; do not commit credentials
savoroute ingest --provider openai --model YOUR_MODEL_ID \
  --sources path/to/freeform_sources.json \
  --new-catalog --output data/generated/catalog.json \
  --provenance data/generated/evidence.json
```

This adapter uses the Responses API. The model must produce the documented JSON extraction structure. API access and cost are not included in the offline tests.

### Ollama

```bash
# Start a local Ollama server and make a compatible model available separately.
savoroute ingest --provider ollama --model YOUR_LOCAL_MODEL \
  --sources path/to/freeform_sources.json \
  --new-catalog --output data/generated/catalog.json \
  --provenance data/generated/evidence.json
```

The adapter calls `/api/generate` with `format: "json"`; `--ollama-url` overrides the default `http://127.0.0.1:11434`. Its endpoint must be explicitly trusted if changed to a remote host. Even a syntactically valid model response can fail evidence validation; such failures stop ingestion without writing the outputs.

## Limitations

There is no crawler, OCR, page parser, image processing, permission verification, confidence calibration, entity resolution, or human review workflow at this stage. Source collection and redistribution rights remain the responsibility of the dataset producer. Provider output and credentials are not stored in the repository. The provenance sidecar contains quoted excerpts and should be handled as source data, including when nonpublic material is processed.
