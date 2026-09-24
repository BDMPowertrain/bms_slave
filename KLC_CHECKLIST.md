# KLC Compliance Checklist

Use this when creating or reviewing a symbol or footprint for Prism's
catalog (see the main [README](README.md#7-creating-symbols-footprints-and-adding-images),
section 7). Prism checks every submission against KLC (the KiCad Library
Convention) automatically, using `kicad-library-utils`'s checking scripts.
Go through the relevant checklist below before you submit, so nothing gets
caught by that automated check that you could have caught yourself first.

> **A note on precision.** Both official homes of `kicad-library-utils`
> ([github.com/KiCad/kicad-library-utils](https://github.com/KiCad/kicad-library-utils)
> and [gitlab.com/kicad/libraries/kicad-library-utils](https://gitlab.com/kicad/libraries/kicad-library-utils))
> are archived, with 27 branches for different KiCad versions and no single
> current canonical one. Which exact version Prism actually runs server-side
> isn't documented anywhere accessible from this repo. What follows is the
> stable, well-established core of KLC, the part that's been consistent
> across essentially every version of the tool since KiCad 6, not a claim
> that this list is the complete, exact rule set Prism enforces. If Prism's
> check flags something not listed here, that's a real finding: fix it, and
> consider asking a lead to add it to this file.

## Required symbol fields (properties)

Every symbol needs these set correctly before submission. In KiCad's Symbol
Editor, these are the Fields shown in the symbol's Properties dialog
(right-click the symbol → **Symbol Properties**, or the Fields table in the
Symbol Editor itself):

| Field | Required content | Visible on schematic? |
|---|---|---|
| `Reference` | Correct prefix for the part type, e.g. `R?`, `U?` (see the prefix table below); the `?` is what KiCad replaces with a number when the symbol is placed | Yes |
| `Value` | The MPN for ICs and complex parts, or the actual value (`10k`, `100nF`, `32.768kHz`) for simple passives | Yes |
| `Footprint` | Either left blank (only if the part is genuinely footprint-agnostic) or an exact `Library:FootprintName` reference | No, hidden |
| `Datasheet` | A direct link to the manufacturer's PDF, never a product page or distributor listing | No, hidden |
| `Description` (KiCad's internal `ki_description`) | A real, searchable one-line description of what the part actually *is* and *does*, not the MPN repeated back | No, hidden |
| `ki_keywords` | Space-separated search terms (function, package type, common synonyms) so the part is findable by more than its exact MPN | No, hidden |
| `ki_fp_filters` | Footprint name patterns, e.g. `SOIC*` or `SOT-23*`, so KiCad's footprint-assignment tool only suggests sensible candidates for this part | No, hidden |

**Why `Footprint` and `Datasheet` are hidden but `Reference` and `Value`
aren't:** the two visible fields are what a reviewer actually needs to read
off the printed schematic to identify the part. The rest is metadata for
tooling (BOM generation, footprint assignment, the library browser's
search), and clutters the schematic if shown.

## Reference designator prefixes

| Component | Prefix |
|---|---|
| Resistors | `R` |
| Capacitors | `C` |
| Inductors | `L` |
| Diodes | `D` |
| Transistors / FETs | `Q` |
| ICs (logic, analog, MCU, power, driver, interface) | `U` |
| Crystals / oscillators | `Y` |
| Connectors | `J` |
| Switches / buttons | `SW` |
| Test points | `TP` |
| Ferrite beads | `FB` |

## Symbol checklist

- [ ] Symbol name is the exact MPN, or a clear standard generic name if
      there isn't one part number that applies.
- [ ] `Reference` field prefix matches the part type (table above) and
      defaults to a bare prefix with no number, e.g. `U?` not `U1`.
- [ ] `Value` field is set correctly per the table above.
- [ ] `Footprint` field is either blank (deliberately) or points at the
      exact intended footprint in `Library:FootprintName` format.
- [ ] `Datasheet` field is a direct PDF link, not a product page.
- [ ] `Description` (`ki_description`) is filled in with a real, useful
      one-line description, not left blank or just repeating the MPN.
- [ ] `ki_keywords` has enough search terms that someone looking for this
      part by function, not just exact MPN, can actually find it.
- [ ] `ki_fp_filters` lists sensible footprint name patterns for this part.
- [ ] Every pin is numbered to exactly match the datasheet, no gaps, no
      duplicates.
- [ ] Every pin has the correct electrical type set (input, output,
      bidirectional, power input, passive, open collector, no-connect,
      etc.), not left on whatever the default was.
- [ ] Power and ground pins that must always be connected are marked
      **Power Input**, not left as generic passive or input pins.
- [ ] Unused pins are explicitly marked no-connect (small X), not just
      left floating with nothing indicating that's intentional.
- [ ] Pins sit on the 100mil (2.54mm) grid, with a consistent pin length
      across the whole symbol.
- [ ] Body outline uses a consistent, standard line width; no stray or
      overlapping graphic elements left over from editing.
- [ ] Reference and value text don't overlap the symbol body or each
      other, and are a consistent, readable size.
- [ ] No duplicate or overlapping pins at the same location.
- [ ] For multi-unit parts (e.g. a quad op-amp), each unit is split out
      and numbered correctly, with a shared unit for common power/ground
      pins if the part has one.
- [ ] Pin numbers checked against the datasheet's pin table one more time,
      right before submitting.

## Footprint checklist

- [ ] Footprint name follows a clear, consistent convention:
      `SOIC-16_3.9x9.9mm_P1.27mm`-style for standard packages,
      `MPN_Package` for custom ones. Nothing ambiguous or generic.
- [ ] Every pad is numbered to exactly match the schematic symbol's pin
      numbers; this is what makes the netlist resolve correctly.
- [ ] Pad shapes and sizes match the datasheet's mechanical/land-pattern
      drawing, not just eyeballed from a similar part.
- [ ] Pin 1 (or the equivalent orientation marker, a dot, notch, or
      bevel) is clearly marked on the silkscreen layer.
- [ ] A courtyard outline exists on `F.CrtYd` (or `B.CrtYd` for a
      bottom-side part), with a small clearance margin around the part's
      true physical body, not just the pads.
- [ ] Silkscreen graphics don't overlap any pad or exposed copper.
- [ ] The `F.Fab` (or `B.Fab`) layer shows an accurate outline of the
      part's physical body, for assembly reference.
- [ ] Reference designator text is placed somewhere it won't end up
      hidden under the part once assembled, and is a readable size.
- [ ] Value/reference text doesn't overlap pads, the courtyard boundary,
      or where neighboring components are expected to sit.
- [ ] Soldermask and paste clearance/expansion is set sensibly for the
      pad type, not left at some accidental default that bridges pads.
- [ ] For through-hole parts: drill sizes match the datasheet, with the
      correct plated vs. non-plated designation.
- [ ] A 3D model is attached and correctly aligned, scaled, and rotated
      to match the real part, if one is available.
- [ ] Footprint checked against the physical part with calipers (pad
      pitch, body size) before committing, especially for anything drawn
      by hand from a datasheet rather than downloaded from a vendor.

## Full official rule set

[klc.kicad.org](https://klc.kicad.org) and the
[kicad-library-utils](https://github.com/kicad/kicad-library-utils)
repository (the `klc-check/` scripts there are the basis for what Prism
runs against your submission). This file covers what people actually get
wrong most often, not the complete spec.
