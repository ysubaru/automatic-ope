## [MEDIUM] HP OO credentials taken from URL query and written to API log

`targets/api-gw/API-Proxy-code/hybrid/proxies/hpoo-prod/apiproxy/policies/Basic-Authentication-1.xml:6` · credential exposure / sensitive data in logs · confidence 0.85

### Impact

Operators' HP Operations Orchestration usernames and passwords travel in URLs and are persisted in the gateway's central API-log pipeline (Azure Event Hubs and GCS) as well as intermediate nginx and OO access logs. Anyone with log access can harvest credentials for a remote-execution engine. The defect is identical in hpoo-staging.

### Description

Basic-Authentication-1 reads `request.queryparam.username`/`password`, Base64-encodes them into Authorization, and forwards. The query parameters are never removed, so the target URL `https://proxy.api.ntt.com/hpoo-prod/oo/rest/v2/executions<pathsuffix>?username=..&password=..` still carries them. Before this policy runs, FC-Oauth2Authentication executes the sharedflow's save-message (save-message.xml line 15), which stores `request.querystring` into `org.request.querystrings` unconditionally; SF-ApiLog_Formatter/resources/jsc/setResponse.js lines 53/99 place that into `requestQueryParameters` of apilogdata, and SC-Send-ApiLog (PostClientFlow) ships it to `/v1/sendapilog` → Event Hubs/GCS without scrubbing. The flag that would suppress query logging is set only in register-admin-v2 and iam-v2. hpoo-staging is byte-identical apart from the base path, and the same query-credential pattern appears in AC_ATLAS-API, AC_OSB-IF and kcc_cti.

### Exploit scenario

An integrator calls `POST /hpoo-prod/?username=oo_admin&password=S3cret` as the proxy design requires. The password appears in clear text in the Event Hubs/GCS log record (requestQueryParameters), in proxy.api.ntt.com access logs, and in the OO server's request log. Anyone with bucket, Event Hub or SIEM read access reuses the credentials to launch arbitrary OO flows.

### Preconditions

- Read access to the API-log sink, the intermediate reverse-proxy logs, or the OO access logs

### How to fix

Credentials must never travel in the URL or be logged. Accept OO credentials only via the Authorization header or an opaque body field; if query params must be kept, add an AssignMessage Remove QueryParams step for username/password right after Basic-Authentication-1 and set `apilog.requestQueryParameters` to false before FC-ApiLogFormatter in both hpoo-prod and hpoo-staging. Rotate OO credentials already present in logs.

### Adversarial verification

**Verdict:** TRUE_POSITIVE (confidence: 9/10) — Query-string credentials are copied verbatim into requestQueryParameters of the API log shipped to Event Hubs/GCS, and also forwarded in the target URL; no filter flag, removal policy, or masking applies to hpoo-prod/hpoo-staging.

Read hpoo-prod default.xml, targets, all policies (Basic-Authentication-1 reads request.queryparam.username/password; no Remove QueryParams anywhere in the tree), SF-Oauth2Authentication (save-message and AM-SaveMessage_Streaming copy request.querystring to org.request.querystrings unconditionally; AM-RemoveAuthirizationHeader strips only the bearer), SF-ApiLog_Formatter (setResponse.js lines 53/99; flag only set in register-admin-v2 and iam-v2), SF-RemoveHeader, SF-RestoreMessage, SF-ApigwVariable, sendApiLog (re-serialises without scrubbing; SC-SendLogToAzure/Gcs), README, diff hpoo-prod vs hpoo-staging (basepath/URL only). PreFlow order OAuth → AuthorityCheck → Basic-Authentication-1; credentials also travel in the target URL to the relay and OO. Same pattern in AC_ATLAS-API, AC_OSB-IF, kcc_cti.

---

## [MEDIUM] Kompira keToken accepted in query string and logged

`targets/api-gw/API-Proxy-code/hybrid/proxies/aozora_ke_prd/apiproxy/policies/EV-ExtractKompiraInfo.xml:3` · Credential exposure via query string and logging · confidence 0.6

### Impact

The Kompira API token that authorises job execution is accepted in the URL and in the body; both are captured verbatim by the shared API log (`org.request.querystrings` and `request.content`), so anyone with access to the log pipeline can replay jobs against Kompira. Tokens in URLs also leak through proxy and access logs.

### Description

EV-ExtractKompiraInfo reads `keToken` from QueryParam keToken and from `$.keToken` in the JSON body, and the AM-SetKompira*Request policies place it in `Authorization: Token {extractedKeToken}`. The proxy runs FC-ApiLogFormatter, whose script records `org.request.querystrings` and the full `request.content` (captured pre-rewrite by save-message and restored by FC-RestoreMessage), then SC-Send-ApiLog ships it to Event Hubs/GCS. Nothing redacts the token; the `apilog.*` opt-out flags are set only in register-admin-v2 and iam-v2 tree-wide. Every other Kompira integration keeps keToken server-side in config.js; aozora_ke_* is the only design where it rides in the logged query or body. Same in aozora_ke_stg.

### Exploit scenario

A ServiceNow integration calls `POST /v1/aozora_ke_prd?keToken=<kompira-token>`. The token is written to the central API log store; an operator or attacker with read access extracts the token and calls the Kompira API directly or through this proxy to execute or modify jobflows.

### Preconditions

- Legitimate clients send the token through this proxy (by design)
- Read access to the API log pipeline or edge access logs

### How to fix

Secrets must never be carried in the URL or in logged bodies. Remove the QueryParam extraction so the token is only accepted from a header, set the proxy's `apilog.requestParameters`/`apilog.requestQueryParameters` flags to false so the ApiLog formatter does not record the body or query, and strip the token field from `request.content` before the log step. Apply to both prd and stg.

### Adversarial verification

**Verdict:** TRUE_POSITIVE (confidence: 8/10) — keToken is captured pre-rewrite by save-message, restored by FC-RestoreMessage, serialised unredacted by SF-ApiLog_Formatter (no apilog.* suppression in aozora_ke_prd/stg), and shipped verbatim via sendApiLog to Event Hubs/GCS.

Read aozora_ke_prd default.xml, targets, EV-ExtractKompiraInfo, AM-SetKompira{Get,Post,Put,Patch}Request, JS-ExtractJobParameters.js, SC-Send-ApiLog; SF-ApiLog_Formatter setResponse.js, SF-Oauth2Authentication (save-message copies request.querystring/content for every request, strips only the Authorization header), SF-RestoreMessage, SF-RemoveHeader, SF-ApigwVariable, SF-AuthorityCheck; sendApiLog bundle; diff prd vs stg (basepath/URL only). apilog.requestQueryParameters/requestParameters opt-out flags set only in register-admin-v2 and iam-v2 tree-wide; only newlines stripped, no redaction anywhere. Every other Kompira integration keeps keToken server-side in config.js; aozora_ke_* is the only design where it rides in the logged query/body.

---

## [MEDIUM] Body field jobPath concatenated into Kompira target URL

`targets/api-gw/API-Proxy-code/hybrid/proxies/aozora_ke_prd/apiproxy/policies/AM-SetKompiraPostRequest.xml:14` · SSRF / path injection into forward-proxy URL · confidence 0.55

### Impact

A caller can make the gateway issue POST, PUT or PATCH requests (with an attacker-controlled JSON body and Authorization token) to arbitrary paths under the Kompira slug, and, if the relay normalises dot segments, to other slugs and upstreams behind proxy.api.ntt.com. This bypasses the intended restriction to specific Kompira job endpoints.

### Description

EV-ExtractKompiraInfo extracts `$.jobPath` from the request body into `extractedJobPath` with no pattern, type or allow-list. AM-SetKompiraPostRequest, AM-SetKompiraPutRequest and AM-SetKompiraPatchRequest then assign `target.url = https://proxy.api.ntt.com/ke_prod{extractedJobPath}`; AM-SetKompiraGetRequest does the same with `{proxy.pathsuffix}`. The value is used raw, so `?`, `#`, `/../` and percent-encoded dots pass through; SF-SystemProtection's URIPath pattern is a placeholder and SF-AuthorityCheck is childUserFlag-gated. The body is rebuilt from `$.parameters` only, but JS-ExtractJobParameters stringifies whatever object the caller supplied. The relay hosts about a dozen slugs (ke_prod, ke_stg, csnms-dr, csms_auth, sirius, businessportal, ctidb, osb-bizsa, swimmy-v2, snow, a raw IP). Identical in aozora_ke_stg (slug ke_stg). Within-slug path choice is arguably the proxy's design; cross-slug traversal depends on runtime normalisation at the Apigee message processor or nginx, which is not provable statically.

### Exploit scenario

Authenticated caller sends `POST /v1/aozora_ke_prd` with body `{keToken: t, jobPath: /../10.39.83.27/some/internal/endpoint, parameters: {cmd: x}}`. The gateway sends `POST https://proxy.api.ntt.com/ke_prod/../10.39.83.27/some/internal/endpoint` with `Authorization: Token t`; a normalising relay resolves this to the 10.39.83.27 slug. Even without normalisation, any Kompira path (for example other customers' jobflows) can be targeted.

### Preconditions

- Valid OAuth bearer token for the aozora_ke product
- For cross-slug reach: the relay resolves `..` or `%2e%2e` segments before slug lookup; within-slug path control needs nothing further

### How to fix

The path reaching the upstream must be constrained to the known Kompira job endpoints. In EV-ExtractKompiraInfo validate `extractedJobPath` against a strict pattern or explicit list and raise a fault otherwise; apply the same check to `proxy.pathsuffix` for the GET flow; never pass `..`, `?`, `#` or encoded dots. Apply to both prd and stg.

### Adversarial verification

**Verdict:** TRUE_POSITIVE (confidence: 7/10) — Attacker-controlled jobPath is concatenated raw into the forward-proxy target URL with no normalization/allow-list anywhere in the bundle or shared flows, enabling traversal to other backend slugs behind proxy.api.ntt.com.

Read aozora_ke_prd manifest, default.xml, targets, AM-SetKompira{Post,Put,Patch,Get}Request, EV-ExtractKompiraInfo (no Pattern/Type), JS-ExtractJobParameters.xml/.js (touches only parameters), AC-For-Develop (develop only); SF-SystemProtection (JSON patterns XSS-only, URIPath placeholder), SF-AuthorityCheck (childUserFlag-gated, startsWith prefix); README; diff prd vs stg (slug only); grep of proxy.api.ntt.com slugs (ke_prod, ke_stg, csnms-dr, csms_auth, sirius, businessportal, ctidb, osb-bizsa, swimmy-v2, snow, 10.39.83.27). Within-slug path choice is arguably design; cross-slug traversal depends on runtime normalization at Apigee MP or nginx, not provable statically.

---

## [LOW] hpoo forwards any path suffix to shared reverse proxy unvalidated

`targets/api-gw/API-Proxy-code/hybrid/proxies/hpoo-prod/apiproxy/targets/default.xml:28` · path traversal to shared reverse-proxy backends · confidence 0.3

### Impact

hpoo-prod and hpoo-staging have no Flows and no Unknown-Resource guard, so every verb and path suffix is appended to `https://proxy.api.ntt.com/hpoo-prod/oo/rest/v2/executions`. proxy.api.ntt.com also fronts beluga (billing), sirius, webentrydashboard, snow, businessportal and informationapi; dot-segment traversal could let an hpoo consumer reach those sibling backends with only an hpoo token. beluga in particular is called by the bills proxy with only a JSON systemId and no credential.

### Description

The ProxyEndpoint PreFlow does OAuth and authority checks and Basic-Auth encoding, then the default target appends `proxy.pathsuffix` to the fixed URL with no target.url rewrite; SF-SystemProtection's URIPath pattern is a literal placeholder, and API products created via the portal use `apiResources []`, so VerifyAccessToken does not constrain the suffix either. Apigee passes `../` and `%2e%2e` segments through unchanged; nginx normalises them before location matching. The sibling AC_CTIDB-API defeats traversal with a `slice(-1)` on the path, showing the available pattern. The verifier's main counter is that Istio/Envoy's default `normalize_path` collapses `/../` and `%2e%2e` before routing (which would 404 at Apigee), while double-encoding survives Envoy but nginx then decodes to a literal `%2e`; this ingress default is not verifiable from the export. The researcher's example used a GET with query credentials; beluga is a POST JSON API, which does not weaken the issue. Same code in hpoo-staging.

### Exploit scenario

`POST /hpoo-prod/%2e%2e/%2e%2e/%2e%2e/%2e%2e/%2e%2e/beluga/api/GetChargeItem` with a JSON body naming a systemId is forwarded as `https://proxy.api.ntt.com/hpoo-prod/oo/rest/v2/executions/%2e%2e/.../beluga/api/GetChargeItem`, which nginx collapses to `/beluga/api/GetChargeItem`, reaching the credential-less billing backend from an hpoo-authorised app.

### Preconditions

- Valid hpoo-* OAuth token
- Apigee router and ingress do not reject or normalise dot-segments in the incoming path (Envoy's default normalisation likely blocks the simple form)
- Reverse proxy normalises encoded dot-segments before routing

### How to fix

Add explicit Flows for the supported OO REST paths and a terminal Unknown-Resource RaiseFault, or add a JS/RegularExpressionProtection step rejecting any pathsuffix containing `..`, `%2e`, `%2f` or `;` before routing, in both hpoo-prod and hpoo-staging.

### Adversarial verification

**Verdict:** TRUE_POSITIVE (confidence: 5/10) — Unvalidated pathsuffix forwarded to a shared nginx hosting credential-less sibling backends (beluga confirmed); only an unverifiable ingress path-normalization default would block it.

Read hpoo-prod targets/proxies default.xml (Flows empty, no Unknown-Resource RaiseFault, no target.url rewrite), manifest, all 18 policies incl. Basic-Authentication-1; hpoo-staging (identical except basepath); SF-SystemProtection RE-RegularExpressionProtection (URIPath pattern literal placeholder), SF-Oauth2Authentication, SF-AuthorityCheck (childUserFlag-gated); bills config.js (flow.beluga.url on the same relay host) and Set-BELUGA.xml (beluga called with only a JSON systemId S066, no credential); managementAccessFromDP Assign-Message-2/setResponse.js/AC-NginxAccessControl; kvm/readme, README (middle nginx); AC_CTIDB-API modifyUrl.js (slice(-1) defeats traversal). Products created via the portal use apiResources [] so VerifyAccessToken does not constrain the pathsuffix. Counter: Istio/Envoy default normalize_path collapses /../ and %2e%2e before routing (would 404 at Apigee); double-encoding survives Envoy but nginx decodes to a literal %2e. The finding's GET ?username= detail is wrong (beluga is POST JSON) but does not weaken the issue.

---
