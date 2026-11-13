# Catalog contract

## JSON format, version 1

`parse_catalog()` validates the following JSON structure using Python code. The repository does **not** yet publish a standalone JSON Schema document.

```json
{
  "schema_version": 1,
  "dataset": {"name": "fictional-example", "synthetic": true},
  "items": [
    {
      "item_id": "p001",
      "kind": "recipe",
      "title": "Herb Bowl",
      "description": "A fictional grain bowl with herbs.",
      "cuisines": ["Mediterranean"],
      "dietary_tags": ["vegetarian"],
      "ingredients": ["rice", "herbs"],
      "source": "synthetic_demo"
    }
  ],
  "media": []
}
```

The full demo contains 12 records; this example illustrates the format, not the shipped catalog.

### Item fields

| Field | Requirement | Validation |
| --- | --- | --- |
| `item_id` | Required | Unique; pattern `[a-z][a-z0-9_-]{1,63}` |
| `kind` | Required | `restaurant` or `recipe` |
| `title`, `description`, `source` | Required | Nonempty strings |
| `cuisines`, `dietary_tags` | Required | Arrays of nonempty, case-insensitively distinct strings |
| `source_url` | Optional | String with HTTP(S) scheme and nonempty network location; no request is made |
| `location` | Restaurants only | Nonempty string |
| `price_tier` | Restaurants only | Integer from 1 through 4; optional |
| `ingredients` | Optional | Array of nonempty strings; permitted on either item kind |

`location` is required for restaurants and prohibited for recipes. `price_tier` is prohibited for recipes. Unknown keys are rejected at the catalog, dataset, item, and media levels. Blank titles, duplicate item IDs, malformed media records, and references to missing items are rejected.

### Media fields

An optional `media` list contains `media_id`, `item_id`, `kind`, `uri`, `source`, and optional `caption`. `kind` is currently `image`. Media IDs must be unique, and `item_id` must reference an item in the same catalog. The parser validates nonempty URI text but does not open files, verify image formats, or check usage rights. The distributed sample has no media assets. The local media exporter added in v0.6.0 writes portable relative image URIs under `assets/`, and creates a separate provenance report with declared rights and input/output hashes. The canonical catalog parser itself does not validate source-image rights or asset bytes; see [image ingestion](media-ingestion.md).

### Provenance

The fields `source` and `source_url` are record-level labels. The catalog does not store collection timestamps, extraction evidence, licenses, or update history. Text ingestion now writes source identifiers, collection timestamps, content hashes, and quoted evidence into a separate provenance file (`docs/ingestion.md`). A separate source registry now records manual cross-provider identity links and last source-managed item hashes; the catalog schema does not contain these fields. Automated cross-provider entity resolution, durable history, and license-policy enforcement remain unimplemented. See [source identity and updates](entity-identity-and-updates.md).

`synthetic: true` identifies the demonstration dataset. Its restaurants, recipes, prices and tags are fictional. A dietary tag is not evidence of ingredient completeness, allergen safety or nutritional suitability. The catalog contains no live venue information or booking inventory.


## Milestone 3: source observations (schema-v1 catalog unchanged)

An optional sidecar built from an existing matching OSM snapshot stores
website, hours and other permitted source-tag observations separately from
the canonical catalog, with digest and source-element linkage. It is not a
trusted extension of `CatalogItem`; the API and frontend label its content
unverified. An independent quality report counts genuinely recorded fields
and flags the generic OSM description as non-informative. See
[data-quality-and-source-facts.md](data-quality-and-source-facts.md).
