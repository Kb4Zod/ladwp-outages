# 01: Colour-code each incident by LADWP status, with restored incidents shown green

**What to build:** Each outage row on the page carries a coloured status chip and short description, keyed by LADWP's status (matched case-insensitively by prefix; unknown → grey "Unknown status"):

| Status prefix | Colour | Description |
|---|---|---|
| REPORTED OUTAGE | red | An outage has been reported in your area |
| ASSIGNED | blue | Repair crew has been assigned and is in queue to be dispatched |
| CREWS EN ROUTE | yellow | Repair crew is on the way |
| CREWS WORKING | purple | Repair crew is on-site working to restore power |
| (restored) | green | Repair is complete |

An outage that was present at the previous successful check and is absent from the current successful check is treated as restored: it is kept in a `recently_restored` list in the state file with its last known customers and a `restored_at` timestamp, shown on the page as a green "Repair complete" row (with "restored h:mm PM") for 24 hours, then dropped. Restored rows are not counted in the banner's outage/customer totals. A failed (stale) check never moves anything to restored. A one-line legend of the five chips with tooltips sits under the list. Colours must be readable on the existing light background; use text + colour, not colour alone.

**Blocked by:** None (can start immediately)

**Status:** done

- [ ] Each active outage row shows a coloured chip with the status text and the description above; prefix matching handles `ASSIGNED - IN QUEUE FOR DISPATCH` etc.; unknown statuses render grey
- [ ] Outages missing from a successful check move to `recently_restored` (id, customers, last status, `restored_at`), render as green "Repair complete" rows, and expire after 24 h
- [ ] Stale/failed checks do not alter `recently_restored`; banner totals exclude restored rows; the banner reads "No outages" when only restored rows remain
- [ ] Legend of five chips with descriptions as tooltips under the list
- [ ] Old state files without `recently_restored` still load
- [ ] Unit tests at the existing seam: each status prefix → class; unknown → grey; restored detection across two checks; 24 h expiry; stale check leaves restored untouched; totals exclude restored
- [ ] `python3 -m unittest` passes; stdlib only; mobile layout intact
