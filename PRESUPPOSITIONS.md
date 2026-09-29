# Design decisions

How contributor isolation works, why it uses this design, and what it does not
support yet.

## Operating rules

- Each contributor has access to one dataset. Country is part of a record's
  identity; it does not control access.
- Calling the promotion function approves the selected record. There is no
  second approval step.
- The app view contains all published records. Publication does not mean a site
  passed a suitability check.
- Database setup expects an empty database and unused role names in a dedicated
  cluster. Public database privileges are removed throughout that cluster.
- Administrators manage objects and access. They are trusted to act outside the
  restrictions placed on contributor, promoter, and app accounts.

## Choices and reasons

| Choice | Reason |
|---|---|
| Separate staging schemas | Keep dataset permissions easy to inspect. |
| Contributors can insert and read, but cannot edit or delete | Keep records stable during review. |
| Non-login object owners | Keep ownership separate from user accounts. |
| A restricted promotion function | Limit core writes to one defined operation. |
| Publish one record per call | Make the approval identify an exact dataset, country, and source ID. |
| Keep staging rows and skip already-published records | Allow retries without deleting source records or overwriting results. |
| Require 2D MultiPolygons in EPSG:4326, source dates, and uncertainty text | Give both datasets the same input rules. |
| Check the supplied SRID explicitly | Reject unknown CRS instead of silently assigning one. |
| Check longitude/latitude bounds in staging and core | Reject impossible degree coordinates, including projected coordinates labelled EPSG:4326. |
| Grant database connections explicitly | Keep runtime accounts out of other databases provided by the PostGIS image. |
| Test actual password-authenticated connections | Check login behavior and permissions together. |

## Current limits and possible extensions

| Current behavior | Possible extension |
|---|---|
| Four predefined login accounts | Individual accounts for each person or service |
| Passwords supplied through local environment settings | Managed secrets, password rotation, and TLS |
| One-time bootstrap plus an explicit hardening migration | Automated migration tracking and general upgrade/rollback procedures |
| One-record approval with no stored approval history | Versioned batches, recorded approvals, and audit logs |
| No workflow for changing published data | Explicit corrections tied to a reviewed version |
| Country-code format checks only | A country registry and geographic checks where needed |
| Coordinate bounds cannot detect every incorrect CRS label | Source-specific CRS verification before ingestion |
| Two fixed dataset layouts | Source adapters that validate and normalize incoming data |
| Direct SQL access | An API for ingestion or application queries |

Row-level security is not used because each dataset has its own table and grants.
Spatial screening and reporting can use the published view as an input; they are
separate features.
