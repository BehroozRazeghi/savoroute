# Source-tagged Boston restaurant preview — November 2026

This directory contains a **real, historical OpenStreetMap-derived dataset**, not a
live restaurant directory and not a set of independently verified businesses.
It is supplied as a **separate, opt-in catalog**; the project's default fictional
catalog and its tests are unchanged.

## Source and collection

- Original source: OpenStreetMap contributors through an Overpass JSON snapshot.
- Original snapshot time: **2026-11-11T21:22:47Z** (`osm3s.timestamp_osm_base`).
- Collection recorded in the original project: **2026-11-12T13:34:43Z**.
- Original 165 mapped `amenity=restaurant` source elements.
- Selected **123 records** with a name and an **explicit** `addr:city=Boston` tag,
  excluding the one record marked `access=private`.
- 41 records without an explicit Boston city tag are **not** silently assigned to Boston.
- Data fields: OSM identifier and source URL, name, source-provided display address,
  explicitly tagged city, recorded cuisines, and OSM coordinates. No proprietary
  restaurant photos, reviews, menu contents, opening-hour assertions, current prices,
  ratings, availability, or dietary/allergen claims have been imported.

The snapshot was provided in a prior user-owned SavoRoute development archive;
this transformation did **not** fetch live OSM or verify that businesses are open
as of today. Some listings may be closed, relocated, incomplete, or inaccurate.
Avoid claiming that a record was manually validated.

## Licensing and obligations

**The dataset is licensed under the Open Database License (ODbL) 1.0**, not the
application's MIT code license. The source is
[© OpenStreetMap contributors](https://www.openstreetmap.org/copyright).
Read the [ODbL](https://opendatacommons.org/licenses/odbl/1-0/) and
[OSM attribution guidance](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines).
Attribution and applicable derivative-database availability/share-alike
obligations must remain in place if this data is redistributed or served publicly.
Do not merge it with restricted-licence third-party restaurant databases without
reviewing the resulting database rights. No separate restaurant permissions were
requested or obtained; OSM's open license permits reuse subject to its terms.

## Start the real-data preview

From the repository root, after building `webapp` and installing the API extra:

```bash
savoroute web serve \
  --catalog data/real/boston-osm-2026-11.json \
  --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/app/>. The **restaurant** search and `Boston` facet
operate on the 123 source-tagged records. The recipe tab has no records because
none were supplied; it must not show invented recipes. All records retain their
OSM source link, and current operating details remain unverified.

For AI-host tool access using a **local MCP-capable client**:

```bash
savoroute mcp serve --catalog data/real/boston-osm-2026-11.json
```

This launches a local stdio MCP server, **not** a public remote MCP endpoint.
