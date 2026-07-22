<!--
SYNTHETIC DOCUMENT — authored for SentinelGrid (InnovaHack), not a real
regulatory or plant procedure. Framed around the Tennessee Eastman Process
benchmark's generic component labels (A-H) and equipment (reactor,
separator, stripper, condenser, compressor). See CLAUDE.md §14 "Is this
real incident data?" guidance: TEP physics are real and published; this
procedure text is not.
-->

# SOP-REACT-001: Reactor High-Pressure / High-Temperature Response

**Equipment:** Continuous-stirred-tank reactor, exothermic gas-liquid reaction of feeds A, C, D, E producing liquid products G and H, with by-product F.
**Trigger conditions:** Reactor pressure (XMEAS 7) trending above 2900 kPa gauge, OR reactor temperature (XMEAS 9) trending above 122°C, OR both trending upward together over a sustained window even if neither has individually crossed its hard alarm limit (2705 kPa / 120.4°C is the normal base-case operating point; the hard high-pressure trip is 3000 kPa gauge, and the hard high-temperature trip is 175°C).

## Why compound trending matters more than either reading alone

A slow, simultaneous rise in both reactor pressure and reactor temperature — even while both remain individually "in range" — is the earliest observable signature of a reaction-kinetics deviation (elevated conversion rate driving more exothermic heat release than the cooling jacket is sized to remove at its current cooling-water flow setpoint). Waiting for a single-variable alarm to trigger before responding routinely means responding only after the reactor is already within 5-10% of its hard trip limits, leaving little margin for a controlled recovery. Operators should treat a joint upward trend in XMEAS(7) and XMEAS(9), sustained over multiple consecutive analyzer/measurement cycles, as an actionable early warning in its own right.

## Response steps

1. **Confirm the trend is real, not sensor noise.** Check that both XMEAS(7) and XMEAS(9) show sustained (not single-sample) upward movement, and cross-check reactor cooling water outlet temperature (XMEAS 21) — a rising outlet temperature with a stable or falling cooling water flow (XMV 10) indicates the cooling loop is being asked to remove more heat than it currently is.
2. **Increase reactor cooling water flow (XMV 10)** toward its upper operating range in a stepwise, not abrupt, manner, monitoring for the temperature trend to arrest within 15-20 minutes.
3. **Check for reaction kinetics drift.** If cooling water flow increases are not arresting the trend, review recent Compound-Risk Agent assessments for a possible slow-kinetics-drift signature (gradual increase in per-unit-feed conversion without a corresponding step change in any single feed or utility variable) — this pattern does not respond to cooling alone and may require a controlled feed rate reduction.
4. **If reactor pressure continues to approach 3000 kPa gauge** despite steps 2-3, reduce reactor feed rate (A and C feed, XMV 3/4) in a controlled ramp-down to reduce reaction heat generation directly, rather than waiting for the automatic high-pressure trip to engage.
5. **Escalate to the Emergency Agent's recommended-intervention workflow** if pressure or temperature crosses 95% of its hard trip threshold at any point — this requires explicit human approval before any recommended action is executed; SentinelGrid never executes a plant action autonomously.
6. **Log the event** with the operator ID, the readings that triggered the response, and the action taken, to the audit trail, regardless of whether the trend was ultimately confirmed as a real deviation or false alarm.

## Related documents
- MSDS-COMP-A (Component A feed hazard data)
- SOP-COOL-002 (Cooling Water System Inspection & Valve Maintenance)
