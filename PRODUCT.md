# Product

## Register

product

## Users

**Primary: installers / resellers** in the RU/UZ market who provision a fixed
app set onto specific car head units (FAW B70, Dongfeng MAGE) for paying
customers. Technical enough to run ADB, plug in USB, and do repeat installs.
Context: at a bench or sitting in the car, on a laptop running Chrome, sometimes
over the car's Wi-Fi. They do this often and want to move fast.

**Secondary: one-time owners** who bought a single unlock for their own car and
run the flow once.

**Job to be done:** pay, get approved, then reliably push a verified set of apps
onto the head unit while seeing exactly what is happening at every step, certain
that nothing will brick the unit.

## Product Purpose

A paywalled provisioning instrument. One approved session installs a fixed,
hash-verified app set onto one head unit over ADB (USB for the Dongfeng MAGE,
wireless for the FAW B70). The web client is a thin executor: the recipe and the
payload live on the server and reach the browser only for the lifetime of one
paid session. Success is a clean install every time, with the operator feeling in
total command and certain of what ran.

## Brand Personality

A precision instrument, not an app. Three words: **precise, engineered, alive.**
Voice is terse and technical, the register of a good CLI: no marketing, no
reassurance padding, every word load-bearing. Telemetry-forward. The interface
earns trust by showing the machine work (each op, each SHA-256, device props, the
live ADB stream) rather than by claiming safety in copy. It should feel like a
tool built by people who know exactly what they are doing.

## Anti-references

- **Sketchy APK / warez / mod sites.** Neon download buttons, fake urgency,
  countdowns, ad slots. This is the single most damaging look for this product.
- **Generic SaaS dashboard.** Card grid, hero-metric tiles, purple gradient,
  rounded-everything. The default AI-slop template.
- **Crypto / hacker neon-on-black.** Matrix green, glowing terminals as
  decoration, edgy-for-its-own-sake. The lazy "power-user" reflex, explicitly out.
- **Enterprise gray forms.** Bootstrap-era gray inputs, lifeless bureaucratic
  layout. The opposite of bold.

**The tightrope:** terminal-native in *behavior* (monospace numerics, streaming
logs, keyboard-first, dense telemetry) but never terminal-native as *costume*.
The energy of a professional instrument, none of the hacker-green cosplay.

## Design Principles

1. **The machine is legible.** Show what actually runs: every op, every hash,
   device props, the raw ADB lines. Trust is earned by exposure, not asserted by
   copy. The most beautiful object on screen is a verified hash going green.
2. **Instrument, not wizard.** Dense, fast, keyboard-first. Respect the
   operator's expertise; do not hand-hold or pad with explanation they don't need.
3. **Precision over decoration.** Every element is load-bearing. Boldness comes
   from typographic authority and confident structure, not ornament.
4. **Correctness is the aesthetic.** Make verification visible and satisfying:
   the step going from queued to running to done, the checksum matching, the
   device answering. That progression is the show.
5. **Bold without the costume.** Distinctiveness through an unexpected but
   disciplined system, not through borrowed subculture signals (neon, matrix,
   warez). If it reads as a genre cliche, it has failed.

## Accessibility & Inclusion

Target WCAG 2.1 AA. Primary surface is desktop Chrome / Edge (WebUSB is required
for the USB car), responsive down to laptop widths. Never signal step state by
color alone: pair every state with a glyph or shape and a text label, so red/green
is not the only channel. Respect `prefers-reduced-motion`: the "alive" telemetry
must degrade to a calm, static equivalent. Keyboard-navigable end to end, matching
the power-user framing. Maintain AA contrast on all text including the monospace
telemetry.
