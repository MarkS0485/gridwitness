# GridWitness: turn your energy meters into a citizen grid sensor network (GB) — would you run it?

**TL;DR:** I'm building an open-source HACS integration that lets your existing Home Assistant sensors (Shelly, Tasmota/ESPHome, Emporia, inverters, even weather stations) contribute anonymous grid-frequency measurements to a citizen-science map of the GB electricity grid. Frequency sharing reveals nothing about your home and is the default. Everything more sensitive is an explicit, revocable opt-in. Your postcode never leaves the server. Before I push this out, I want to know: would you run it, and what would you want to see?

## The idea

The National Grid publishes one frequency trace for the whole country. A handful of professional phasor units (PMUs) cost thousands of pounds each, so nobody has a *dense, nationwide* picture of what the grid is actually doing moment to moment.

But a lot of us already measure the grid at home. A Shelly Pro 3EM, an Emporia Vue, an ESPHome board with a CT clamp, or a solar inverter all read frequency, voltage, and power many times a second. Individually that is noise. Four hundred of them, timestamped and pooled, is something nobody currently has: geographic density across the whole island.

GridWitness is the plumbing to make that pooling easy, and honest about privacy.

## What it does

You install the integration from HACS. It auto-discovers your relevant sensors by `device_class` (voltage, current, power, frequency, and weather ones like temperature, humidity, wind, pressure, irradiance). You then choose, per channel, what you are willing to share, and how precisely you want to be located. It batches readings and pushes them every ~30 seconds to an ingest server. If the server or your internet is down it buffers to disk and backfills on reconnect, so gaps heal themselves.

There is a local dashboard card too: your frequency trace over the national one, your contribution stats, and how far your clock drifts. Retention is the point. If it is not interesting to leave running, it is not worth your electricity.

## The privacy deal (this is the important bit)

I did not want to build another thing that quietly hoovers up household data. So the design has one rule: never ask for anything I cannot justify to a thoughtful person. Here is the honest breakdown.

- **Grid frequency** is the same number for everyone connected to the GB grid at a given instant. Sharing it tells us nothing about your house, because it is identical whether measured at your place or next door. This is the default, and on its own it is genuinely useful.
- **Voltage** is a reading about your local feeder, not about you. Low sensitivity.
- **Current and power** are the sensitive ones, and I will say so plainly: your load reveals when you are home, asleep, cooking, or charging a car. This is **off by default**, never bundled with anything else, and offered with coarser options. The reason to share it at all is that a node that also shares its own power becomes self-calibrating, which is scientifically valuable. If that trade is not worth it to you, do not share it. Frequency alone still helps.
- **Weather** (if you have a station) is outdoor conditions, not behaviour. It helps model how weather drives demand and renewables.

Location is a separate, tiered choice: anonymous (rough region only, no address), region (you pick your grid area from a list), or data-share (you enter a postcode). In data-share mode the postcode is used once on the server to derive a coarse grid-area code and is then kept server-side and never published. I am honest about the ceiling: even then it pins to a grid supply point or primary substation, not your street.

Node IDs are random. The only place anything private lives is the server's local database (hashed token, the postcode, the node-to-you link), and none of that is ever written into the shared dataset. The integration is open source specifically so you can check that this is true rather than take my word for it.

Timestamps are all UTC, disciplined against multiple NTP servers so your readings line up with everyone else's even if your host clock drifts.

## Honest status and caveats

- This is early (call it a P0). It works end to end in testing, but I have not opened public onboarding yet.
- It is **GB-grid specific** for now. The concept generalises to any synchronous grid, but the calibration and location mapping are built around GB. If you are outside GB and interested, say so, that changes my priorities.
- The ingest server is self-hosted (I will run one on a fixed line at home). It is a small FastAPI service, so you could also run your own.
- Nothing here competes with professional monitoring. It is the thing the professionals do not have: breadth.

## What I'm asking (this is a request for interest)

Before I invest in onboarding, docs, and a public server, I want a reality check from people who actually run this hardware:

1. **Would you leave this running?** What would make you trust it enough to, or not?
2. **What hardware would you point at it?** Meter model, single or three phase, inverter brand, weather station.
3. **Privacy:** does the per-channel, opt-in, postcode-stays-server-side model feel right, or is there a line I have got wrong?
4. **The give-back:** what would make the local dashboard worth keeping? Event catches ("you saw the 14:32 dip 400 ms before London"), a live frequency map, contribution streaks?
5. **Anything that would stop you** dead: an ISP quirk, an add-on vs integration preference, a data-retention worry, a "why not just use X".

Blunt feedback is more useful than polite feedback. If the answer is "nobody wants this", that is worth knowing now.

## Links

- Code and design: https://github.com/MarkS0485/gridwitness
- The full design doc and the privacy statement are in the repo.

Thanks for reading. Happy to answer anything in the thread.
