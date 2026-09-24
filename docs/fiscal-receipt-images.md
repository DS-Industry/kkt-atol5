# Fiscal receipt images

`/qr` and signed `/qr/<id>/<signature>.png` render the stored fiscal document,
not a reconstructed sale. `?plain=1` retains the original QR-only image.

Additive migration: nullable TEXT `check.fiscal_document`. The successful
queue transaction stores the complete getFnDocument JSON alongside its QR.
Receipt items, totals, payment breakdown, tax tags, fiscal identifiers and
cashier (only if present in the TLV) come from that immutable snapshot.
Additional registration/cliche context is captured separately via read-only
driver requests. It never overrides fiscal TLV, payments or cashier fields.

Historical rows lacking the full document remain QR cards explicitly marked
as incomplete. A backfill must read that exact FN document and verify the QR
matches the stored row before writing. Historical registration context, when
added, is labelled as a snapshot taken during recovery, not historical proof.
No HTTP image request communicates with the KKT or issues another receipt.

The UI fits receipt width and scrolls vertically to preserve legibility.
Existing PLC response fields and fiscal printing call sequence are unchanged.
