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

An optional `media` list contains `media_id`, `item_id`, `kind`, `uri`, `source`, and optional `caption`. `kind` is currently `image`. Media IDs must be unique, and `item_id` must reference an item in the same catalog. The parser validates nonempty URI text but does not open files, verify image formats, or check usage rights. The distributed sample has no media assets.

### Provenance

The fields `source` and `source_url` are record-level labels. They do not record collection time, licenses, extraction evidence, field-level provenance, or update history. Those requirements belong to the ingestion work and will be implemented before accepting third-party records.

`synthetic: true` identifies the demonstration dataset. Its restaurants, recipes, prices and tags are fictional. A dietary tag is not evidence of ingredient completeness, allergen safety or nutritional suitability. The catalog contains no live venue information or booking inventory.
