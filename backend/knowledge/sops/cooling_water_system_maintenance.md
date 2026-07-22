<!--
SYNTHETIC DOCUMENT — authored for SentinelGrid (InnovaHack), not a real
regulatory or plant procedure. See CLAUDE.md §14.
-->

# SOP-COOL-002: Cooling Water System Inspection & Valve Maintenance

**Equipment:** Reactor cooling water jacket and control valve (XMV 10), condenser/separator cooling water circuit and control valve (XMV 11).
**Trigger conditions:** Reactor cooling water valve (XMV 10) or condenser cooling water valve (XMV 11) commanded position shows erratic, non-monotonic swings that do not correspond to a deliberate setpoint change, OR cooling water outlet temperature (XMEAS 21 / XMEAS 22) fails to move in the expected direction relative to a valve position change.

## Recognizing valve stiction vs. a genuine cooling demand change

A control valve responding normally to a real change in cooling demand moves smoothly toward a new position and settles; the corresponding outlet water temperature moves with it in a consistent direction. Valve stiction — mechanical binding that causes a valve to not track its commanded position smoothly — instead produces position readings that jump, overshoot, or fail to correlate cleanly with the outlet temperature response. Because the affected reactor or condenser temperature reading itself often stays within its normal operating band throughout (the control loop is still able to "fight" the sticking valve well enough to avoid a large process excursion, at least initially), this fault is easy to miss if operators are only watching temperature and pressure alarms rather than valve position trends directly.

## Inspection and maintenance steps

1. **Trend the affected valve's commanded position (XMV) against its corresponding measured outlet temperature (XMEAS) over the same window.** A healthy valve shows a consistent, monotonic relationship; a sticking valve shows position swings with an inconsistent or lagging temperature response.
2. **Cross-check against recent setpoint change history.** If no operator or supervisory-loop setpoint change occurred in the relevant window, valve position movement of more than roughly 10 percentage points should be treated as unexplained.
3. **Schedule a physical inspection** of the valve actuator, packing, and positioner at the next opportunity. If the erratic behavior is worsening shift-over-shift (increasing swing amplitude, or the associated process variable beginning to trend rather than merely oscillate), escalate the inspection to before the next shift rather than the next scheduled outage.
4. **Do not attempt to compensate for a suspected sticking valve by retuning its PI loop gain.** A more aggressive gain on a mechanically sticking valve typically worsens the oscillation rather than correcting it; the fix is mechanical, not a control-tuning change.
5. **If reactor or condenser temperature begins a sustained trend** (not just oscillation) while the associated valve shows stiction symptoms, treat this as an escalation per SOP-REACT-001 in addition to the mechanical maintenance action here — the two procedures are complementary, not alternatives.
6. **Log every valve stiction flag** to the audit trail with the specific valve (XMV 10 or XMV 11), the observed swing magnitude, and whether maintenance was scheduled immediately or at next outage.

## Related documents
- SOP-REACT-001 (Reactor High-Pressure / High-Temperature Response)
