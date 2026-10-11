# Intake enrichment

Intake saves sanitized heuristic data first. A background supervisor bounds the
LLM call by the total LLM_TIMEOUT budget (default 120 seconds). The setting must
be a positive finite number; invalid settings produce a class-only warning and
use the default. On timeout, transport failure, thread startup failure, or save
failure, pending clears and heuristic data remains available. Late transport
results cannot invoke the save callback. A timed-out daemon transport can remain
alive until the underlying call returns.

Pending state assumes a single-process deployment. Completed supervisor handles
are pruned on the next request. A restart implicitly clears pending state.

Each asynchronous field is applied only if its current value equals the intake
snapshot, including empty values. A changed posting URL invalidates the whole
result. Successful enrichment sets enriched to true.

Company URL matching normalizes host case, trailing dots, and default ports.
Shared ATS hosts are declared once in server.SHARED_ATS_HOSTS; host matching
also requires the same first path segment, ignoring case. Existing company
websites and linked posting URLs can identify an ATS tenant. ATS URLs are never
auto-filled as company websites. Explicit company-name matches remain supported.
A corrected LLM company name re-points an unchanged company link when an existing
company matches. Otherwise only the text changes, and the retained link is
flagged for review in a history event. The correction and event are saved
together. Contact email fill follows the final company link and preserves
existing company email.

ingest.REDACTION_PATTERNS is the single redaction policy for extracted strings,
nested lists, and metadata. It rejects private/link-local address patterns
(requiring at least three octets, so prose decimals such as "10.5" survive) and
IPv6 link-local strings. Rejected LLM values preserve heuristic fields.
Rejected extracted values become empty; rejected websites remain unset or use a
safe non-ATS posting origin. Owner-entered text is outside this extraction
policy. Posting vocabulary such as provider names and times is never redacted:
the no-provider-naming rule covers our docs and PRs, not posting content.
Contact addresses must also pass the shared email validator; mailto
scanning continues past invalid addresses.

Background extraction and save failures log one line containing only an
exception class, with no exception message or traceback.
