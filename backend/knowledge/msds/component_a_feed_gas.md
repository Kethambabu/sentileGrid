<!--
SYNTHETIC DOCUMENT — authored for SentinelGrid (InnovaHack). "Component A"
refers to the generic reactant gas feed in the Downs & Vogel (1993)
Tennessee Eastman Process benchmark (stream 1), not a real named chemical.
Hazard data below is illustrative, not a real regulatory MSDS/SDS. See
CLAUDE.md §14.
-->

# MSDS-COMP-A: Component A — Reactant Feed Gas

**Identity:** Component A, light reactant gas feed (process stream 1), fed to the reactor via the A feed valve (XMV 3) either directly or blended with Component C via the A&C feed valve (XMV 4).

**Physical state:** Gas at process conditions.

## Hazard summary

- **Flammability:** Flammable gas. Forms a flammable mixture with air across a wide concentration range. Any unplanned release into an occupied area should be treated as an ignition-source-control emergency, not merely an environmental release.
- **Reactivity:** Reacts exothermically with Components C, D, and E under reactor conditions (catalyzed, elevated pressure) to form liquid products G and H, with by-product F. This is the intended reactor chemistry — the hazard concern is an *uncontrolled* rate of this same reaction, not the reaction itself.
- **Pressure hazard:** Normally handled as a compressed gas feed at multi-bar pressure; a failed feed valve or line rupture presents both a flammable-release hazard and a pressure-hazard (whipping line, rapid decompression) at the failure point.
- **Asphyxiation:** Displaces oxygen in enclosed or poorly ventilated spaces; treat any large release in an enclosed area (e.g. a valve gallery) as an asphyxiation hazard in addition to the flammability hazard.

## Relevance to compound-risk monitoring

A drop in measured A feed flow (XMEAS 1) while the A feed valve (XMV 3) is commanded open (or opening) is the signature of a supply-side loss, not a demand-side change — see the reactor_a_feed_loss near-miss incident for a worked example of this exact signature, and SOP-REACT-001 for the associated response procedure. This combination (valve open, measured flow flat) should be treated as a higher-priority signal than either reading alone, since a fully-open valve rules out a control-loop explanation for low flow.

## First response (non-exhaustive; defer to full plant emergency procedures for actual response)

Isolate the affected feed line at the nearest upstream isolation point if a leak is confirmed; do not attempt to restart feed flow into a suspected leak point without confirming line integrity first.
