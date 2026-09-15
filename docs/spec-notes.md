# dseng 1.4.1 spec notes

Source: `docs/openapi/dseng-1.4.1.json` (OpenAPI 3.1.0, Engineering Web Services 1.4.1).

## Base URL and headers
- On-premise style: `{3DSpace}/resources/v1/modeler/dseng`. The spec also lists `{APIGateway}/api/dseng/v1`.
- `SecurityContext` header is required on **every** call (`Role.Organization.CollabSpace`).
- `ENO_CSRF_TOKEN` header is required on every write (POST/PATCH/DELETE). Get it from `3DSpace/resources/v1/application/CSRF`.
- Error body: `{"status": int, "message": str}`.

## PATCH /dseng:EngItem/{ID}  (schema `dseng_EngItem_PATCH`)
- **`cestamp` is required** in the body. It comes back on GET and search with any mask.
- Writable: `title`, `description`, `versionComment`, `isManufacturable`,
  `dseng:EnterpriseReference.partNumber`, `dseno:EnterpriseAttributes`, `customerAttributes`,
  `dslc:changeControl`, `dscfg:Configured`.

## Search: differs from the plan
- It's `GET /dseng:EngItem/search` with `$searchStr`, `$mask`, `$top` (default 50, max 1000), `$skip`.
  There is **no POST search with a JSON body** in dseng. Results stop after 100000.
- Properties with empty values are **left out** of search responses. A missing key means empty,
  and that matters for detecting missing attributes.
- Search masks: `dskern:Mask.Default`, `dsmveng:EngItemMask.Common`, `dsmveng:EngItemMask.Details`.
  Details adds `isManufacturable`, `dseng:EnterpriseReference`, `dseno:EnterpriseAttributes`, `reservedBy`.
- Filter-style queries (Advanced Filter) belong to the 3DSpace common/search services, not this file.

## Material
- Material is **not an attribute**. It is a `dsspec:Material` relationship:
  `GET /dseng:EngItem/{ID}/dsspec:Material`, `POST .../dsspec:Material/attach`, `.../detach`.

## BOM structure
- `GET /dseng:EngItem/{ID}/dseng:EngInstance` with `$mask=dsmveng:EngInstanceMask.Details` returns
  `referencedObject` (the child item) and `dsxcad:findNumber`.
- `POST /dseng:EngItem/{ID}/expand` walks the whole structure in one call.
- `POST /dseng:EngItem/locate` does where-used (parents of an item).

## Create
- `POST /dseng:EngItem` with body `{"items": [{"type": "...", "attributes": {"title": ...}}]}`, max 50 per call.
  `title` is required.

## Tenant parameter (found by testing, not in the dseng spec)
- The cloud 3DSpace answers `401 tenant 'r…' does not exist` unless `?tenant=R1132101930766` is sent.
  This applies to the CSRF call and to every modeler call. The client adds it automatically.
- The 3DPassport CAS login itself works. The `/enovia/?ticket=` landing page returns 403, but the session cookies are set.
- `GET /resources/modeler/pno/person?current=true&select=collabspaces&tenant=…` lists your roles and collab spaces.
  The organization's internal name is `Company Name` (title: University of Oulu).

## Verified against the tenant (Phase 3 seeding)
- Item create accepts `dseng:EnterpriseReference.partNumber` in `attributes`.
- **Batch create bug:** in one `POST /dseng:EngItem` with several items, an item *without* a part number
  inherits the previous item's part number. `seed_items.py` now creates one item per call.
- `DELETE /dseng:EngItem/{ID}/dseng:EnterpriseReference` clears a part number (GET then shows `partNumber: ""`).
- **BOM link reference format differs from the spec examples.** The spec's `"$3DSpace"` and
  `/dseng:EngItem/{id}` are rejected. Accepted:
  `{"source": "<PLM_SPACE_URL>", "type": "dseng:EngItem", "identifier": id, "relativePath": "/resources/v1/modeler/dseng/dseng:EngItem/{id}"}`.
- Items created in one run share the same `cestamp` value, so cestamp is not unique per item.
- `POST /dseng:EngItem/locate` works for where-used, with the same reference format as BOM links.
- **`GET .../dseng:EngInstance` does not return instances in creation order.** The part number rule
  therefore uses only the set of sibling numbers, never their position.

## Phase 3 assumptions not yet verified against the tenant
- PATCH with `description: ""` clears the description (used when a proposal is rejected).

## Still needed
- Common (Security Context, CSRF) and 3DPassport specs, to replace the empirical login notes above.
