# Rehearsal: PolicyLens homepage preview

Gold: `static-card` from Stageshow. Kept its one cropped product window and one result card; changed the content, colors, Korean typography, width, and compact layout for PolicyLens.

Medium: a still image beside the working upload form on desktop, below it on mobile. The image is an authored example, not a live model result.

Focal object: an ambiguous AI-use clause. Payoff: the three roles identify the missing default rule, followed by a revision guideline.

Captured: 500 × 380 wide stage, 358 × 360 compact stage at a 390px host viewport. Look: light green, opaque cards. Reduced motion is the same still.

Gate: both `film.mjs --still --gate` runs ended `film: no-issues-detected` and `rehearsal passed` (exit 0).

Film findings and fixes: removed cropped toolbar text, stopped overriding the kit row geometry, aligned result-card gutters, raised compact text to at least 10px, and removed the missing favicon request. The gold example itself reported a lopsided row under the current checker; it was used as a visual reference, not shipped.

Review: inspected both rendered stills. The quote, issue, role positions, and guideline are visible without card overlap. The mobile result card is a full-width lower sheet.

Functional check: the still was exported to `server/static/`; the upload form and debate calls remain part of Django. The existing 26 server tests and Django system check passed after integration. Stageshow's host layout check reported no issues at 1280px and 390px.

Not checked: no animation or cursor interaction was authored. This asset does not display document-specific output.
