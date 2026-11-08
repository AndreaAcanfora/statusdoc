# Open Status Document (OSD) — version 0.1

Status: draft. Feedback welcome through GitHub issues.

The key words MUST, MUST NOT, SHOULD, SHOULD NOT and MAY are to be
interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

## 1. Purpose

Almost every online service has a status page, and many of them publish the
same information as JSON: an overall indicator, components, open incidents and
planned maintenance. Programs read it to show upstream health on dashboards,
pause deploys during a provider outage, route traffic away from a degraded
region or explain an error to a user.

Two things are missing:

1. **A written specification.** Most JSON status documents share a shape,
   the `summary.json` popularized by Atlassian Statuspage and mirrored by
   other providers (incident.io, for example), but it is documented only as
   one vendor's API. Field meanings, required fields and enumerations are
   learned by reading examples, and other providers use different formats
   entirely, so aggregators maintain one parser per provider.
2. **Discovery.** Given a domain such as `github.com`, no program can find its
   status document: the status page lives on another domain
   (`www.githubstatus.com`), and the mapping is kept by hand.

OSD addresses both. It specifies the existing shape, so that most documents
already published conform with no or minor changes, and it adds discovery
from a service's own domain.

## 2. Terminology

- **Service**: the product whose status is published, identified by a domain.
- **Status page**: the human-readable page.
- **Status document**: the JSON document defined in section 4.
- **Publisher**: whoever serves the status document.
- **Client**: a program that reads status documents.

## 3. Discovery

### 3.1 Well-known URI

A service SHOULD serve a discovery document at
`https://{domain}/.well-known/status`, where `{domain}` is the domain users
know the service by:

```json
{
  "osd_version": "0.1",
  "document": "https://www.githubstatus.com/api/v2/summary.json",
  "page": "https://www.githubstatus.com"
}
```

- `document` (REQUIRED): absolute `https` URL of the status document.
- `page` (RECOMMENDED): absolute URL of the human status page.
- `osd_version` (RECOMMENDED): the OSD version of the document.

Instead of a discovery document, the well-known URI MAY serve the status
document itself, or redirect to it. A client tells them apart by the
presence of the `status` and `components` members.

The response MUST use `Content-Type: application/json` and SHOULD carry
`Access-Control-Allow-Origin: *`. Clients MUST follow at most 5 redirects and
MUST NOT follow a redirect from `https` to another scheme.

### 3.2 HTML link

The home page of a service MAY point to its status document with:

```html
<link rel="status" type="application/json" href="https://status.example.com/api/v2/summary.json">
```

### 3.3 Fallbacks (informative)

While discovery is not widely deployed, clients find documents by
convention. Many status pages serve their document at
`{page}/api/v2/summary.json`, and many services host their page at
`status.{domain}`. Clients MAY try these, and MAY ship a list of known
services. A discovered well-known document always wins over a list.

## 4. Status document

A status document is a JSON object, encoded as UTF-8 and served with
`Content-Type: application/json`. Timestamps are strings in RFC 3339 format
(`2026-11-08T08:28:32.963Z`). Members that are not defined here MUST be
ignored by clients; publishers MAY add them.

### 4.1 Top level

| Member                   | Required    | Contents                                  |
|--------------------------|-------------|-------------------------------------------|
| `page`                   | REQUIRED    | Page object (4.2)                         |
| `status`                 | REQUIRED    | Status object (4.3)                       |
| `components`             | REQUIRED    | Array of components (4.4), may be empty   |
| `incidents`              | REQUIRED    | Array of unresolved incidents (4.5)       |
| `scheduled_maintenances` | RECOMMENDED | Array of upcoming and active maintenance (4.6) |
| `osd_version`            | RECOMMENDED | `"0.1"`                                   |

### 4.2 Page

| Member       | Required    | Contents                                  |
|--------------|-------------|-------------------------------------------|
| `name`       | REQUIRED    | Name of the service                       |
| `url`        | REQUIRED    | URL of the human status page              |
| `updated_at` | REQUIRED    | Time of the last change to the document   |
| `id`         | OPTIONAL    | Publisher's identifier of the page        |
| `time_zone`  | OPTIONAL    | IANA time zone used on the human page     |

### 4.3 Status

| Member        | Required | Contents                                       |
|---------------|----------|------------------------------------------------|
| `indicator`   | REQUIRED | `none`, `minor`, `major`, `critical` or `maintenance` |
| `description` | REQUIRED | Short human summary, e.g. "All Systems Operational" |

`indicator` is the overall state of the service, as judged by the publisher.
It SHOULD NOT be less severe than the impact of any unresolved incident
(section 5). It need not match the worst component: one location of a
service with hundreds of them can be down while the service as a whole is
only partially affected.

### 4.4 Components

| Member        | Required    | Contents                                     |
|---------------|-------------|----------------------------------------------|
| `id`          | REQUIRED    | Stable identifier (string)                   |
| `name`        | REQUIRED    | Display name                                 |
| `status`      | REQUIRED    | Component status, see below                  |
| `updated_at`  | RECOMMENDED | Time of the last status change               |
| `description` | OPTIONAL    | Text or null                                 |
| `position`    | OPTIONAL    | Display order (integer)                      |
| `group`       | OPTIONAL    | `true` if the component groups others        |
| `group_id`    | OPTIONAL    | `id` of the group this component belongs to, or null |
| `components`  | OPTIONAL    | For groups: array of member component ids    |

Component status, from best to worst:

| Value                  | Meaning                                    |
|------------------------|--------------------------------------------|
| `operational`          | Working normally                           |
| `under_maintenance`    | Planned work in progress                   |
| `degraded_performance` | Working, but slow or with elevated errors  |
| `partial_outage`       | Unavailable for some users or features     |
| `major_outage`         | Unavailable                                |

Component ids MUST be stable across documents, so that clients can watch a
specific component.

### 4.5 Incidents

`incidents` lists the incidents that are not resolved. A publisher MAY
include recently resolved incidents with status `resolved` or `postmortem`.

| Member             | Required    | Contents                                          |
|--------------------|-------------|---------------------------------------------------|
| `id`               | REQUIRED    | Stable identifier                                 |
| `name`             | REQUIRED    | Title                                             |
| `status`           | REQUIRED    | `investigating`, `identified`, `monitoring`, `resolved` or `postmortem` |
| `impact`           | REQUIRED    | `none`, `minor`, `major` or `critical`            |
| `created_at`       | REQUIRED    | Creation time                                     |
| `updated_at`       | RECOMMENDED | Time of the last update                           |
| `started_at`       | OPTIONAL    | When the problem started, if earlier              |
| `resolved_at`      | OPTIONAL    | Resolution time, or null                          |
| `shortlink`        | OPTIONAL    | URL of the incident on the human page             |
| `incident_updates` | RECOMMENDED | Array of updates, newest first                    |
| `components`       | RECOMMENDED | Array of affected components, with their status   |

An update has `id`, `status` (as the incident), `body` (text) and
`created_at`, all REQUIRED, and MAY have `display_at` and `updated_at`.

### 4.6 Scheduled maintenance

`scheduled_maintenances` lists maintenance that is planned or in progress.
Each item has the members of an incident, with these differences:

- `status` is `scheduled`, `in_progress`, `verifying` or `completed`;
- `scheduled_for` and `scheduled_until` (REQUIRED) give the planned window.

### 4.7 Unknown values

Future versions may add values to the enumerations. A client that meets an
unknown value MUST NOT reject the document. It SHOULD treat an unknown
component status as `degraded_performance`, an unknown impact or indicator
as `minor`, and an unknown incident status as unresolved.

## 5. Severity (informative)

To summarize a document, clients and publishers can order states as follows:

| Severity | Indicator     | Component status        | Incident impact |
|----------|---------------|-------------------------|-----------------|
| 0        | `none`        | `operational`           | `none`          |
| 1        | `maintenance` | `under_maintenance`     | —               |
| 2        | `minor`       | `degraded_performance`  | `minor`         |
| 3        | `major`       | `partial_outage`        | `major`         |
| 4        | `critical`    | `major_outage`          | `critical`      |

The overall level of a service is its indicator, raised to the impact of any
unresolved incident and to `maintenance` while maintenance is in progress.
Clients that watch specific components compare the component statuses
directly.

## 6. HTTP

- Status documents and discovery documents MUST be served over HTTPS.
- They SHOULD carry `Access-Control-Allow-Origin: *`, so that dashboards in
  a browser can read them. They are public by nature.
- They SHOULD carry `Cache-Control` with a `max-age`, and an `ETag` or
  `Last-Modified` header.
- Clients SHOULD send conditional requests (`If-None-Match`,
  `If-Modified-Since`), SHOULD NOT poll a document more often than its
  `max-age` allows, and SHOULD NOT poll more often than every 30 seconds
  by default.
- Clients SHOULD identify themselves with a `User-Agent` that includes a way
  to contact their author.

## 7. Security considerations

- Text members (`description`, `body`, names) are written by people and may
  contain HTML or Markdown. Clients MUST NOT render them as HTML without
  sanitizing them.
- Publishers MUST NOT put anything in a status document that is not meant to
  be public, such as internal host names.
- Clients that act on status (pausing deploys, failing over) SHOULD treat a
  document they cannot fetch as unknown, not as an outage, and SHOULD
  require a state to persist across more than one poll before acting.
- Clients MUST bound the size of the documents they read.

## 8. Conformance

- A **conforming publisher** serves a status document that follows section 4
  over HTTP as in section 6, and SHOULD serve discovery as in section 3.
- A **conforming client** follows sections 3, 4.7 and 6.

The reference implementation ships a validator:
`statusdoc validate <url-or-domain>`.

## 9. Versioning

Minor versions (0.x) only add optional members and enumeration values, which
clients already handle by section 4.7. Breaking changes require a new major
version.

## Appendix A. Relation to existing formats (informative)

OSD follows the `summary.json` shape of Atlassian Statuspage, which other
providers also serve. Such documents usually conform already, except for
`osd_version`. Discovery (section 3) is new.

An expired IETF Internet-Draft, *Service Status Resource Format for Web
Services* (`draft-dallariva-web-service-status-json-00`), proposed a new
format. OSD takes the opposite approach: it specifies the format that is
already deployed.
