# Board Template

<p align="center">
  <img alt="BDM Logo" src="Logos/bdm_logo.png" width="30%">
&nbsp; &nbsp; &nbsp; &nbsp;
  <img alt="SAE Electric Logo" src="Logos/SAE_Electric_Logo.png" width="30%">
</p>

A KiCad 10 project template for Blue Devil Motor Sports boards: automated
fabrication/assembly documentation via
[KiBot](https://github.com/INTI-CMNB/KiBot), and review, component
governance, and semantic diffing via
[Prism](https://github.com/krishna-swaroop/KiCAD-Prism).

**This is the template's own README.** Once a real board repo is created from
this template, its `README.md` gets **replaced by CI on the first run** with
a short, live-generated board summary (logo, CI badge, current 3D renders,
dimensions) that links back to this file. See
`kibot_resources/templates/readme.txt`. Read this file *before* that first CI
run, or open it at
[github.com/BDMPowertrain/KiCad_10_Template](https://github.com/BDMPowertrain/KiCad_10_Template)
any time afterward.

Based on [nguyen-v/KDT_Hierarchical_KiBot](https://github.com/nguyen-v/KDT_Hierarchical_KiBot),
adapted for KiCad 10 only, Prism-native component management (no local
symbol/footprint libraries), and a single self-contained repo per board.

**This guide assumes you've never used git or KiCad before.** Every command
is spelled out, so you never need to guess what to type. Wherever a git or
KiCad concept comes up for the first time, there's a short plain-English
explanation right there. If you already know git and KiCad, skim past those
boxes.

## Table of Contents
- [1. Before You Start](#1-before-you-start)
- [2. One-Time Computer Setup](#2-one-time-computer-setup)
- [3. Starting a New Board](#3-starting-a-new-board)
- [4. The Daily Loop](#4-the-daily-loop)
- [5. The One Rule That Matters Most](#5-the-one-rule-that-matters-most)
- [6. Writing a Good Commit Message](#6-writing-a-good-commit-message)
- [7. Creating Symbols, Footprints, and Adding Images](#7-creating-symbols-footprints-and-adding-images)
- [8. Getting Your Work Reviewed](#8-getting-your-work-reviewed)
- [9. Moving the Board Through Its Stages](#9-moving-the-board-through-its-stages)
- [10. Releasing a Board](#10-releasing-a-board)
- [11. When Something Goes Wrong](#11-when-something-goes-wrong)
- [12. Rules (Things That Will Get You Yelled At)](#12-rules-things-that-will-get-you-yelled-at)
- [13. Reference](#13-reference)

---

## 1. Before You Start

### What this project actually is

A "board" here means one PCB (printed circuit board): one physical part of
the car, like a sensor board or a control unit. Each board gets its own
GitHub repository (a "repo"; think of it as one project's folder, tracked
online with the full history of every change anyone's ever made to it).
This template is the starting point for every one of those repos. It comes
with the file structure, the automation, and the house rules already set up,
so nobody starts from a blank page.

Two tools do the heavy lifting:
- **KiCad**: the actual program you draw the schematic and PCB layout in.
- **KiBot**, running automatically in the cloud every time you push a
  change: it turns your KiCad files into the documents a fabrication house
  or a teammate actually needs (PDFs, gerbers, the manufacturing format PCB
  fabs read, bills of materials, 3D renders). You never run this yourself.

### A short glossary

You'll see these words constantly. Read this once now; you won't need to
memorize it, just recognize it later.

| Word | What it means here |
|---|---|
| **git** | The tool that tracks every change to every file in this project and lets multiple people work on it without overwriting each other. Everything below is git doing its job. |
| **repo** (repository) | This project's folder, plus its entire tracked history. |
| **clone** | Downloading a copy of a repo onto your computer for the first time. |
| **commit** | A saved snapshot of your changes, with a short message describing what you did. Commits are the individual "save points" that make up a repo's history. |
| **branch** | A separate line of work inside the same repo, so people don't overwrite each other. This project uses two: `dev` (everyone works here day to day) and `main` (reserved for finished, released work). |
| **push** | Sending your commits from your computer up to GitHub, where everyone else can see them. |
| **pull** | Downloading everyone else's latest commits down to your computer. |
| **merge conflict** | What happens when two people change the same part of the same file and git can't automatically combine both changes. You resolve it by hand. |
| **CI / CI/CD** | "Continuous Integration," an automated robot (GitHub Actions, in this project) that runs every time you push, generating documents and checking your work. You'll see it referred to as "CI" throughout. |
| **variant** | Which stage of the design process a board is in: `DRAFT`, `PRELIMINARY`, `CHECKED`, or `RELEASED`. Controls what CI generates. See [section 9](#9-moving-the-board-through-its-stages). |
| **tag** | A permanent label on one exact point in history, used here to mark an official release (e.g. `1.0.0`). Pushing a tag is what triggers a release; see [section 10](#10-releasing-a-board). |

### Where to go from here

- **Setting up a brand-new board from scratch?** Read sections 2 and 3 in
  order.
- **Joining a board someone else already started?** Do section 2 (one-time
  computer setup) once, then skip straight to section 4. Someone else has
  already done section 3 for that board.

## 2. One-Time Computer Setup

Do this once per computer, not once per board. If you're joining a board
someone else already created, do this section, then jump to
[section 4](#4-the-daily-loop). Skip section 3, that part's already done.

### 2.1 Install KiCad 10

Download from [kicad.org/download](https://www.kicad.org/download/). Default
install options are fine; just click through the installer.

### 2.2 Install the project fonts and color theme

The schematics and PCBs in every BDM board use specific fonts and a custom
color theme that don't come with a stock KiCad install. Without this step,
everything still opens and works; it'll just look wrong (substitute fonts,
wrong colors). Do this once, from any board repo (the files are identical in
every one, so it doesn't matter which board you grab them from):

**Fonts** (`kibot_resources/fonts/*.ttf`, Arial and Times New Roman
variants):
- **Windows**: select all the `.ttf` files in that folder, right-click, then
  **Install**.
- **Linux**: `cp kibot_resources/fonts/*.ttf ~/.fonts/ && fc-cache`

**Color theme** (`kibot_resources/colors/Altium_Theme.json`):
- **Windows**: copy it to
  `C:\Users\<you>\AppData\Roaming\kicad\10.0\colors\`
- **Linux**: `cp kibot_resources/colors/Altium_Theme.json ~/.config/kicad/10.0/colors/`

### 2.3 Install git

> **What is this step doing?** You're installing the git *program* on your
> computer so you can use the `git` commands you'll see throughout this
> guide. It's separate from GitHub (the website): git is the tool, GitHub is
> where this project's repos are hosted.

- **Windows**: download from [git-scm.com](https://git-scm.com/download/win)
  and use the default install options. This also installs **Git Bash**. Use
  it (found in your Start Menu after installing) as your terminal for every
  command in this guide, not PowerShell or cmd.exe. The commands shown here
  assume Git Bash.
- **Mac/Linux**: git is usually already installed. If not,
  [git-scm.com](https://git-scm.com/downloads) has instructions.

Check it worked: open your terminal and type `git --version`. It should
print a version number, not an error.

### 2.4 Connect KiCad to Prism and log in

Prism is where this team's component library lives. Instead of every board
repo carrying its own copy of every symbol and footprint, KiCad fetches them
live from Prism when you place a part. This works through KiCad's "Remote
Symbol Provider" feature, and it takes two pieces: a package that adds the
Remote Symbols panel to KiCad, and a link that tells that panel which Prism
server to actually talk to.

1. The datasource package is shipped right in this template, at
   `Prism_Plugin/kicad-prism-remote-symbols.zip`. It's built from the Prism
   server and is specific to this team's deployment; you don't build it
   yourself, and you don't need to track down a lead to hand it to you.
2. In KiCad 10, open **Plugin and Content Manager**. Install that `.zip`
   package from there (look for an option to install from a file rather than
   the online repository).
3. Open **Preferences → Hotkeys** and add **Remote Symbols** to a short cut. Shift + A is a good one.
4. Open a schematic and open the **Remote Symbols** panel. Paste the Prism provider link prism.lokislair.com. This is the piece that actually points the panel at this
   team's Prism server. 
   When prompted, your system browser opens for you to log in with your Pocket ID passkey. Once that completes, the panel is connected.

> **Note:** the exact menu wording can shift slightly between KiCad
> versions. If a menu name above doesn't match what you see, look for
> "Plugin and Content Manager" and "Manage Symbol Libraries" specifically;
> the panel that appears after installing the package is where the actual
> connection happens.

**Verify it worked:** open any board's schematic, **Place → Symbol**, search
for "resistor," confirm it shows up as coming from Prism, then delete it
(you were just testing, not actually placing a part).

**If the library shows as unavailable:** check your internet connection
first. Prism is self-hosted, so it may just be down for maintenance; wait a
few minutes and retry. You can still open and view an *existing* board with
no connection at all (KiCad embeds the symbol data already in the
schematic), you just can't place new parts or browse the catalog. This
matters most the night before competition, so check then, not the morning
of. If it's down more than 15 minutes, message a lead. **Don't create a
local placeholder symbol instead**; see
[section 12](#12-rules-things-that-will-get-you-yelled-at).

### 2.5 Committing parts you've placed from Prism

Every time you place a part from the Remote Symbols panel, KiCad writes a
local copy of that part's symbol, footprint, and 3D model into
`RemoteLibrary/` at the project root, along with entries in `sym-lib-table`
and `fp-lib-table` pointing at them. **Commit all of these.** It's tempting
to treat `RemoteLibrary/` as a disposable cache and ignore it, but Prism's
own release build treats a missing footprint entry there as a warning sign,
meaning a clean checkout is expected to already have these files, not
regenerate them on the spot. If they're missing, the next person to clone
the repo gets broken symbol/footprint references until someone manually
re-places every part.

**Before you commit, check `sym-lib-table` and `fp-lib-table` for absolute
paths.** Open them in a text editor; each `(lib ...)` line has a `(uri ...)`
field. It should look like:

```
(uri "${KIPRJMOD}/RemoteLibrary/symbols/remote_example.kicad_sym")
```

not like:

```
(uri "C:/Users/yourname/Git/board_repo/RemoteLibrary/symbols/remote_example.kicad_sym")
```

An absolute path (a full drive letter and folder path, specific to your
computer) works fine for you, but breaks for everyone else who clones the
repo to a different location, since that exact path won't exist on their
machine. If you see one, replace everything from the drive letter through
`RemoteLibrary` with `${KIPRJMOD}`, keeping the rest of the path after it
the same. This is also worth a second look any time you add a part that
isn't from Prism (a personal local library folder can end up in
`fp-lib-table` the same way, and that one won't resolve for anyone else at
all, `${KIPRJMOD}` won't fix a reference to something outside the repo).

## 3. Starting a New Board

Do this once, when a board doesn't have a repo yet. If you're joining a
board that already exists, skip to [section 4](#4-the-daily-loop) instead.

1. On GitHub, click **Use this template → Create a new repository**
   (top of this template's page). Name the new repo after the board:
   lowercase, underscores for multi-word names, no year/car prefix (e.g.
   `tim`, `bse_apps`, `tim_tempsense`).

2. **Clone it** (download a copy onto your computer) **and create the `dev`
   branch.** "Use this template" only creates the `main` branch; `dev`
   doesn't exist yet, and every daily-workflow command in this guide assumes
   it does, so this step isn't optional. In Git Bash:

   ```
   git clone https://github.com/BDMPowertrain/<board>.git
   cd <board>
   git checkout -b dev
   git push -u origin dev
   ```

   > **What did that just do?** `git clone` downloaded the repo.
   > `cd <board>` moved your terminal into that new folder; every command
   > after this point in this guide assumes you're inside the repo folder.
   > `git checkout -b dev` created the `dev` branch and switched you onto
   > it. `git push -u origin dev` uploaded that new branch to GitHub so
   > everyone else can see and use it too.

3. **Run the setup script.** This is the only supported way to set the
   board's name, metadata, and stage. Never hand-edit the config files it
   touches (more on that in [section 13](#13-reference)).

   ```
   ./configure.sh --init
   ```
   (Windows users can instead just double-click `configure.bat` in the
   repo's folder, in File Explorer, instead of typing the command.)

   It'll ask you a series of questions in the terminal: board name, a
   human-readable title, a one-line description, your name as designer,
   company (defaults to Blue Devil Motor Sports), an initial revision
   number, and whether to enable an extra impedance-table output (only
   relevant if this board has controlled-impedance traces; if you don't know
   what that means, answer no). It then renames the project files and fills
   in the metadata for you. Nothing else needs hand-editing.

4. **Commit and push what it changed.** The script prints the exact
   commands to run when it's done; copy-paste them. This lands on `dev`,
   which is exactly where it should be. `main` stays as the pristine
   template snapshot until your first release; don't commit directly to it (see [section 5](#5-the-one-rule-that-matters-most) and
   [section 12](#12-rules-things-that-will-get-you-yelled-at) for why that
   matters).

5. Connect KiCad to Prism and register the repo with Prism; see
   [section 2.4](#24-connect-kicad-to-prism-and-log-in) if you haven't
   already done this on this computer.

6. In Plane (the team's project-tracking tool): create the board's Low
   Level work item under the **ELEC** module (in this season's car
   project) and link this repo to it.

Read the rest of this guide before your first commit, especially
[section 5](#5-the-one-rule-that-matters-most).

## 4. The Daily Loop

This is what you do every single time you sit down to work on a board that
already has a repo set up. Everyone works directly on the `dev` branch;
there's no need to make a new branch for each change.

**Every time you start working, run this first:**

```
git checkout dev
git pull
```

> **What's happening here?** `git checkout dev` makes sure you're on the
> right branch (in case you were somewhere else last time). `git pull`
> downloads everyone else's changes since you last worked. Teammates may
> have pushed commits while you were away, and you want to start from the
> latest version, not an outdated one.

**Make your changes in KiCad.**

Before committing a **schematic** change, run ERC (Electrical Rules Check:
KiCad checking your schematic for electrical mistakes, like unconnected
pins or conflicting outputs):

**Inspect → Electrical Rules Checker → Run ERC**, fix anything it flags.

Before committing a **layout** change, run DRC (Design Rules Check: KiCad
checking your PCB layout against manufacturing constraints, like traces
being too close together):

**Inspect → Design Rules Checker → Run DRC**, fix anything it flags.

**Then save your work with git:**

```
git add <the specific files you changed>
git commit -m "SCH[tim-can]: add ISOW1044 isolated CAN transceiver, channel 1"
git push
```

> **What's happening here?** `git add` tells git which changed files you
> want to include in this save point (you can also use `git add .` to
> include everything you changed; that's fine for most cases here). `git
> commit` actually creates that save point, with a message describing what
> you did (see [section 6](#6-writing-a-good-commit-message) for the exact
> format to use; it's not optional on this project). `git push` uploads it
> to GitHub so everyone else can see it and CI can run.

Watch the repo's **Actions** tab on GitHub. CI runs automatically on every
push and shows a green checkmark (passed) or a red X (something failed; see
[section 11](#11-when-something-goes-wrong)).

**When your board is ready to become a release candidate:** get it reviewed
(see [section 8](#8-getting-your-work-reviewed)), then a lead tags it (see
[section 10](#10-releasing-a-board)). There's no separate merge step; the
tag push handles getting everything onto `main` on its own.

## 5. The One Rule That Matters Most

**KiCad's schematic and PCB files (`.kicad_sch` and `.kicad_pcb`) cannot be
merged.**

git is built to combine two people's changes to the same text file
automatically; that's what a "merge" is. KiCad's files are technically
text, but their internal structure means git's merge algorithm produces
garbage if two people edit the same file at the same time. Not "annoying to
fix," actually broken, unusable output.

**The rule: one person edits a given sheet or board file at a time.**

- Before editing a hierarchical sheet (e.g. `Section A - Title A.kicad_sch`,
  one of the sub-pages of the schematic) or the PCB layout, claim it:
  comment on the board's Plane work item ("claiming CAN sheet") or move a
  sub-task to "In Progress" with your name on it.
- When you're done and pushed, release it: mark the sub-task done, or
  comment "released CAN sheet."
- If you need to edit something someone else is actively working on, ask
  them first; don't just start.

This is a process rule, not something git enforces for you automatically.
Breaking it is the single most disruptive thing you can do to teammates'
work; it can cost someone hours of redone work.

## 6. Writing a Good Commit Message

Every commit message on this project follows one format:

```
TYPE[scope]: summary
```

**Types:**

| Type | Use for |
|---|---|
| `SCH` | Schematic changes |
| `LAYOUT` | PCB layout/routing changes |
| `LIB` | Requesting/placing components from Prism's catalog |
| `DOCS` | README, CHANGELOG, notes, templates |
| `CI` | Workflow, `kibot_yaml/` changes |

**Scope:** the board name plus the sheet or section, e.g. `tim-can`,
`tim-power`, `tim-mezzanine`, or just `tim` for something board-wide. This is
a free-form label inside the commit message, not a repo name, not
case-sensitive, just something that tells a reviewer where to look.

**Rules that make reviewing this project's history actually possible:**
- Never mix a schematic change and a layout change in one commit. They're
  different files, a reviewer might care about each separately, and Prism
  (the review tool) diffs them separately too.
- Commit after each logical change, not once at the end of a session. A
  3-hour session on the CAN sheet should be several commits, not one giant
  one.
- Run ERC before every schematic commit, DRC before every layout commit
  (see [section 4](#4-the-daily-loop)).

**Worked examples, what makes a good message vs. a bad one:**

| Good | Bad | Why the bad one hurts |
|---|---|---|
| `SCH[tim-can]: add ISOW1044 isolated CAN transceiver, channel 1` | `updated schematic` | Reviewer has to open the whole diff just to find out what changed. |
| `LAYOUT[tim-mezzanine]: route mezzanine connector power plane` | `fixed stuff` | "Fixed" implies a bug: was this a bug or new work? Which sheet? |
| `LIB[tim]: request ASM330LHHG1TR IMU from Prism catalog` | `added part` | Which part? Requested (pending approval) or placed (already released)? |
| `DOCS[tim]: update fabrication notes for 4-layer PCBWay stackup` | `readme` | Doesn't say what changed, or that it's actually the fab notes template. |
| `CI[tim]: tighten ERC severity for unconnected pins` | `update workflow` | A specific, reviewable change; "update" could be anything. |
| `SCH[tim-power]: fix STM32G474 decoupling cap footprint mismatch` | `bug fix` | No indication of severity, which part, or whether it's electrical or footprint. |
| `LAYOUT[tim]: DRC clean pass, 4-layer PCBWay clearances` | `layout done` | "Done" isn't a description of a change: what specifically was fixed to get there? |

## 7. Creating Symbols, Footprints, and Adding Images

### When you need a new symbol or footprint

Every part on a board comes from Prism's catalog (see
[section 2.4](#24-connect-kicad-to-prism-and-log-in)), never from a local
library file, this template deliberately ships with no local symbol or
footprint libraries at all. If a part you need doesn't already exist in
Prism's catalog:

1. Search first; it might be there under a different name than you expect.
2. If it's genuinely missing, it has to be created inside Prism before
   anyone can place it. Whether that's something you do yourself depends on
   whether you have Prism's `designer` role; ask a lead if you're not sure.
   If you don't have it, use the `LIB` commit type (see
   [section 6](#6-writing-a-good-commit-message)) to ask someone who does.
3. Once it's released in Prism, it shows up in the Remote Symbols panel for
   everyone, the same as any other part.

### How a symbol or footprint actually gets made

Most people draw the symbol and footprint locally in KiCad first, since
that's the environment you already know, then bring that into Prism:

1. **Make a temporary local library**, one for symbols and one for
   footprints, just to work in. Name and location don't matter; it never
   gets committed anywhere and nothing in this template reads from it.
   It's scaffolding, not a real library, you're deleting it (or just
   ignoring it) once the part is released in Prism.
2. **Symbol**: in KiCad's Symbol Editor, create the new symbol inside that
   temporary library. Draw it from the datasheet's pin table, or copy and
   rename an existing similar symbol as a starting point. Save.
3. **Footprint**: in KiCad's Footprint Editor, create the new footprint
   inside that temporary library. Draw it from the datasheet's mechanical
   drawing, matching pad numbers exactly to the symbol's pin numbers.
   Save.
4. **Export just that one part**, not the whole temporary library:
   **File → Export → Symbol…** in the Symbol Editor, **File → Export →
   Footprint…** in the Footprint Editor. Each writes a single, standalone
   file containing only that one part. That exported file, not the
   temporary library itself, is what you attach in Prism.
5. In Prism's Library Manager (the web app), use **Manual creation**:
   create the component's identity and metadata, then attach the exported
   symbol and footprint files, plus a 3D model if you have one.
6. Submit it. Prism validates it against KLC (see the next section) as
   part of the review flow. If it comes back with findings: fix them in
   the same temporary library (same symbol or footprint, not a new one),
   save, export again, and re-upload the corrected file. Repeat until it
   passes.
7. Once it clears validation, it moves the rest of the way through
   Prism's review flow (`open` → `in_progress` → `qa_review` → `done` →
   `released`). A teammate with the `qa` role has to approve it, and a
   different person than whoever authored it has to be the one who
   actually releases it, so nothing goes live on one person's say-so
   alone.
8. Once released, it's placeable: it shows up in the Remote Symbols panel
   for the whole team.

### General rules to follow (KLC)

Prism checks every submission against KLC, the **KiCad Library
Convention**, the official design rules KiCad's own libraries follow,
automatically, using the real `kicad-library-utils` checking scripts.
Depending on how your lead has that gate configured, a finding either just
shows as a warning or actually blocks release, so it's worth getting these
right before you submit, not after:

- **Reference designator prefix matches the part type.** `R` for
  resistors, `C` for capacitors, `L` for inductors, `D` for diodes, `Q` for
  transistors/FETs, `U` for ICs, `Y` for crystals/oscillators, `J` for
  connectors, `SW` for switches, `TP` for test points.
- **Pin numbers on the symbol must exactly match the datasheet.** This is
  what makes the electrical connections correct once it's placed; a
  swapped pin number is a real bug, not a cosmetic one.
- **Footprint pad numbers must exactly match the symbol's pin numbers.**
  This is what lets KiCad connect the schematic to the copper correctly. A
  mismatch here doesn't show up until a board comes back wired wrong.
- **Pin 1 (or the equivalent orientation marker) must be clearly marked**
  on the footprint's silkscreen, so it can be placed the right way around.
- **A courtyard outline is required**, on the `F.CrtYd`/`B.CrtYd` layer: a
  box around the part's physical footprint with a small clearance margin.
  Courtyards on a real board should never overlap a neighboring part's
  courtyard; that's how you catch a layout that's too tight to actually
  assemble.
- **Silkscreen should never sit on top of a pad or exposed copper.** It
  won't print correctly there anyway, and it can look like a solder bridge.
- **Verify a hand-drawn footprint against the physical part with calipers**
  before it goes anywhere near a real board. A pad-spacing mistake that
  looks fine on screen can mean a part physically doesn't fit once boards
  come back from the fab, and that costs a full respin.

The full official rule set lives at
[klc.kicad.org](https://klc.kicad.org) and in the
[kicad-library-utils](https://github.com/kicad/kicad-library-utils)
repository (the `klc-check/` scripts there are literally what Prism runs
against your submission).

Before you submit a symbol or footprint, go through
**[KLC_CHECKLIST.md](KLC_CHECKLIST.md)**. It's a separate file so it's easy
to keep open next to KiCad while you work, and it spells out exactly what
must be set in a symbol's properties (Reference, Value, Footprint,
Datasheet, Description, keywords, footprint filters) and what to check on a
footprint, specifically enough to catch what the automated KLC check in
Prism would otherwise catch for you.

### Manually adding pictures to a sheet

Sometimes you want to drop an actual image onto a schematic sheet: a pinout
diagram from a datasheet, a mechanical reference photo, a diagram for a
teammate. KiCad supports this directly:

1. In the schematic editor, **Place → Import Graphics** (or the equivalent
   toolbar icon).
2. Pick an image file (PNG, JPG, SVG, and a few others are supported).
3. Click on the sheet to place it, then resize and position it like any
   other element.

**One thing to know before you do this:** KiCad embeds the image data
directly inside the `.kicad_sch` file itself; it isn't a separate linked
file. A large or uncompressed image can inflate that file's size
dramatically. This repo already has a real example of that: a set of
custom page-layout templates with an embedded logo came in over 1 MB each,
versus a few KB for the same file without one. Compress or resize an image
before importing it if you can, and avoid importing a raw multi-megabyte
photo straight from a phone.

The same **Place → Import Graphics** tool exists in the PCB editor too,
most commonly used for a logo or reference outline on a silkscreen layer.
Make sure you pick the layer you actually intend (silkscreen for a logo,
not a copper layer) using the layer selector before placing it.

## 8. Getting Your Work Reviewed

This project doesn't use GitHub pull requests. `main` is never a place
people merge into by hand; it's only ever updated automatically by the
tag-triggered release process (see [section 10](#10-releasing-a-board)).
Review happens directly on `dev`, through Prism, continuously as you work,
not as a one-time gate before a merge that doesn't actually happen here.

**Leaving a review comment:** open Prism and compare the current state of
`dev` against the last release, click on the specific schematic/PCB/BOM
element you have a question about, and leave a comment there rather than a
generic note elsewhere. It stays attached to that specific element even as
the design changes later. Anyone can leave a comment at any time; reviewers
don't have to wait for a formal request.

**Responding to a comment:** reply in the same Prism discussion thread. If
you made the change it asked for, say so and resolve the thread; if you
disagree, say why and leave it open for the lead to weigh in.

**When a board is ready to move forward** (whether that's changing variant,
see [section 9](#9-moving-the-board-through-its-stages), or a full release,
see [section 10](#10-releasing-a-board)), that's a judgment call your lead
makes, not a merge event. **"Ready" means:** every open discussion in Prism
is resolved, CI is green on `dev`, and `CHANGELOG.md`'s `[Unreleased]`
section actually describes what's changed since the last release.

> **Note:** the exact click path for opening a comparison in Prism without
> an existing pull request isn't nailed down precisely here; ask a lead if
> the option described above doesn't match what you see.

## 9. Moving the Board Through Its Stages

A board moves through four stages, called **variants** here. Each one
controls what CI generates and how strictly it checks your work. You change
a board's variant with `configure.py`, never by hand-editing any config
file:

```
./configure.sh --variant           # opens a menu to pick one
./configure.sh --variant CHECKED   # sets it directly
```

| Variant | CI generates | Roughly when |
|---|---|---|
| `DRAFT` | Netlist, schematic PDF, draft BOM only | Design, early: schematic still being drawn |
| `PRELIMINARY` | Full documentation (fab, assembly, 3D, testpoints), but ERC/DRC don't block the build | Design, late |
| `CHECKED` | Same full documentation, but ERC/DRC **are** enforced; CI fails the build on any error | Procurement/Fabrication |
| `RELEASED` | Same as `CHECKED`, but you never set this by hand; see [section 10](#10-releasing-a-board) | Testing |

**One hard requirement, at every stage past `DRAFT`:** the board needs at
least one via or through-hole part on it before you move past `DRAFT`. A
board with literally zero drillable holes anywhere makes one of KiBot's
underlying tools crash outright. This is a real limitation, not a setting
to change. If you see
`IndexError: list index out of range` / `Layer pair index 0 out of range`
in a failed CI run, this is why; see
[section 11](#11-when-something-goes-wrong).

For the full technical breakdown of exactly what file gets generated at each
stage and why, see [section 13](#13-reference).

## 10. Releasing a Board

**`RELEASED` is never set by hand.** It happens automatically when a **tag**
(a permanent label marking one exact point in history, like `1.0.0`) gets
pushed to GitHub. Only your Electrical Lead does this:

```
git tag 1.0.0
git push origin 1.0.0
```

**What happens automatically after that push**, in order:
1. CI renames `CHANGELOG.md`'s `[Unreleased]` section to
   `[1.0.0] - <today's date>`, and starts a fresh empty `[Unreleased]`
   section for whatever comes next.
2. The board variant is force-overridden to `RELEASED` for this run: full
   documentation, ERC/DRC enforced, same as `CHECKED`.
3. Every generated output (fabrication PDFs, gerbers, assembly docs, 3D
   files, everything from [section 9](#9-moving-the-board-through-its-stages)'s
   table) gets committed and automatically merged into the `main` branch.
4. A GitHub Release is created, with the fabrication/assembly/3D files
   attached directly for download, and the CHANGELOG entry as the release
   description.

**Keep `CHANGELOG.md`'s `[Unreleased]` section up to date as you work.** Add
a real bullet point under `Fixed`/`Added`/`Changed`/`Removed` for each
meaningful change, not just at release time. That's what step 1 above turns
into the permanent release notes; if it's empty or just placeholder text
when you tag, that's what the release notes will say too.

**Not yet automated:** getting that same release-notes text to also show up
*inside* the schematic itself, on the `Revision History` page, is a manual
step your lead does per release: add a new variable pair to
`kibot_yaml/kibot_pre_set_text_variables.yaml` and matching text boxes on
`Revision History.kicad_sch`. This isn't unique to this project; the
upstream template this is based on has the exact same manual step, undone.
Ask a lead if you need this done for a release.

## 11. When Something Goes Wrong

**Merge conflict on `.kicad_pro`:** don't try to hand-merge the JSON inside
it.

```
git status
git pull
```

Let git show you the conflict, then re-run `./configure.sh` (no arguments).
It re-writes the current values on top, resolving the conflict. If you're
not confident about this, stop and ask a lead instead of guessing.

**Realize you're on `main` instead of `dev`:**

```
git status          # confirms you're on main
git checkout dev
git pull
```
Your uncommitted changes come with you onto `dev` automatically; nothing is
lost. (You also can't accidentally push straight to `main`: it's protected,
and only the automated release process is allowed to update it directly.
That rejection is expected, not a bug.)

**Committed a huge binary file by accident:**

If you haven't pushed yet: `git reset HEAD~1` undoes the commit but keeps
your other changes. Remove the huge file, then re-commit properly.

If you already pushed: **stop, don't force-push, message a lead.** History
cleanup on a shared branch needs a lead's judgment call, not yours alone.

**A symbol won't resolve because Prism is unreachable:** see
[section 2.4](#24-connect-kicad-to-prism-and-log-in). Don't create a local
one-off symbol to keep working; wait, or ask a teammate.

**CI failing on ERC/DRC:** open the failed run on GitHub's Actions tab,
download the log artifact, and read what it flagged. Fix it locally
(**Inspect → Electrical/Design Rules Checker** in KiCad), re-run the check,
then commit and push again. Don't lower the variant back to
`DRAFT`/`PRELIMINARY` just to make the red X go away; that hides the
problem, it doesn't fix it.

**CI failing with `IndexError: list index out of range` in
`draw_drill_map` / `Layer pair index 0 out of range`:** your board has zero
drillable holes anywhere (no vias, no through-hole parts); see the note in
[section 9](#9-moving-the-board-through-its-stages). Add at least one via
and push again; this isn't fixable any other way.

**Index/title page on the schematic shows `Error: XML File not found`:**
this means an internal step got run out of order and left bad data
committed into the project file. This shouldn't happen with the current
workflow. If you see it, stop and message a lead rather than trying to fix
it yourself; it needs a specific repair, not a normal commit.

**When in doubt about any of the above:** stop and ask a lead. Never
force-push a shared branch to "fix" something you're not sure about.

## 12. Rules (Things That Will Get You Yelled At)

- **Force-pushing `dev` or `main`.** Ever. If you think you need to, you
  don't; ask a lead.
- **Editing a sheet or board file someone else owns**, without claiming it
  in Plane first (see [section 5](#5-the-one-rule-that-matters-most)).
- **Hand-committing generated outputs** (fabrication PDFs, gerbers, BOMs)
  from a local KiBot run. They do belong in the repo; CI commits them
  itself on every run, but only CI's copy should ever reach the repo. A
  hand-pushed local copy just goes stale the moment someone else's CI run
  overwrites it, and can race with CI's own commit. Let CI do it.
- **Creating a one-off local symbol instead of requesting the part in
  Prism's catalog.** It'll work for you today and break the
  BOM/documentation pipeline for everyone else later.

## 13. Reference

Material you'll look up as needed, not read start to finish.

### Directory structure

```
├─ <board>.kicad_pro/.kicad_sch/.kicad_pcb   # root project, renamed by configure.py
├─ Block Diagram.kicad_sch                    # hierarchical sheets: content
├─ Project Architecture.kicad_sch             # edited freely, filenames never
├─ Power - Sequencing.kicad_sch               # renamed (change the sheet
├─ Revision History.kicad_sch                 # TITLE in KiCad instead)
├─ Section A - Title A.kicad_sch              # synced with CHANGELOG.md
├─ Section B - Title B.kicad_sch
│
├─ configure.py / .bat / .sh          # the setup/variant script and its wrappers
├─ <board>.kicad_dru                  # PCBWay 4-layer design rules, renamed by
│                                        configure.py like the other project files
├─ Templates/                         # drawing sheets (schematic + PCB)
├─ Logos/                             # team + sponsor logos
├─ Prism_Plugin/                      # Prism's KiCad datasource package,
│                                        see Setup section 2.4
│
├─ kibot_resources/
│  ├─ colors/                         # KiCad color theme (install once, see Setup)
│  ├─ fonts/                          # fonts (install once, see Setup)
│  ├─ scripts/                        # helpers KiBot calls at CI time, plus
│  │                                    the maintainer-only local-run scripts
│  └─ templates/                      # fabrication/assembly/README templates
│
├─ kibot_yaml/                        # KiBot config, maintainer-only, don't
│                                       hand-edit; configure.py writes to it
│
├─ kibot_launch.sh                    # maintainer-only: run KiBot locally
├─ CHANGELOG.md                       # hand-maintained, Keep a Changelog format
└─ meta/info.html                     # "New Project From Template" text in KiCad
```

### `configure.py` command reference

The only supported way to change board metadata or move between variants.
Never hand-edit `kibot_main.yaml`, `ci.yaml`, or a `.kicad_pro`'s text
variables. This script owns all of that, and re-running it is always safe.

```
./configure.sh --init              # first-time setup on a fresh template
./configure.sh                     # update board metadata later
./configure.sh --variant           # menu: DRAFT / PRELIMINARY / CHECKED
./configure.sh --variant CHECKED   # set a variant directly
./configure.sh --dry-run           # preview any of the above, write nothing
```

RELEASED is never set by this script; see [section 10](#10-releasing-a-board).

### What each variant actually produces, in detail

KiBot doesn't render anything itself; it's an orchestrator that drives
KiCad's own command-line tools (`kicad-cli`) to do each export, then
optionally post-processes the result (e.g. compressing gerbers into a ZIP,
or splicing a generated table into a PDF). Every run reads the same
`kibot_yaml/kibot_main.yaml`; the variant only changes *which group* of
outputs runs and whether ERC/DRC are enforced.

**`DRAFT`**: just enough to sanity-check a schematic that's still being
drawn:
- `README.md`: the live-generated board summary.
- `<board>.net`: netlist, exported straight from the schematic.
- `Schematic/<board>-schematic.pdf`: full schematic printout.
- `Manufacturing/Assembly/<board>-bom.csv` / `-bom.html`: bill of
  materials, read directly from component fields in the schematic.

**`PRELIMINARY` / `CHECKED` / `RELEASED`**: everything `DRAFT` has, plus:

- **`Manufacturing/Fabrication/`**: the fab package. Gerbers (`Gerbers/`),
  Excellon drill files, an ODB++ ZIP (an alternative fab format some houses
  prefer), a drill map PDF and a drill table CSV, fabrication notes (from
  `kibot_resources/templates/fabrication_notes.txt`), and
  `<board>-fabrication.pdf`, the actual document you'd send to PCBWay. This
  isn't a raw KiCad print: it's the `F.Dimensions`/`DrillMap` PCB layers
  rendered, with the drill table CSV and fabrication notes **spliced into
  pre-placed named groups** on those layers at render time. That's why
  those layers look like they have empty labeled rectangles when you open
  the board in KiCad; KiBot fills them in. Everything above also gets
  zipped into one file for uploading to the fab house directly.
- **`Manufacturing/Assembly/`**: the assembly package. The position file
  (pick-and-place data, CSV), the BOM (CSV/HTML, and an interactive HTML BOM
  you can click through part-by-part), a component-count report, assembly
  notes, and `<board>-assembly.pdf`, using the same splicing trick as the
  fab PDF, but embedding the 3D renders, component count, and DNP
  (do-not-populate) crosses into the `F.AssemblyText`/`TitlePage` layers
  instead.
- **`3D/`** and **`Images/`**: a STEP file (the board's 3D mechanical
  model, for checking enclosure fit) and PNG renders of the actual PCB
  (top/bottom/angled), generated by KiCad's headless 3D viewer. These same
  PNGs are what shows up in the auto-generated `README.md`.
- **`Testing/Testpoints/`**: top and bottom testpoint location tables
  (CSV), also embedded into the fabrication PDF's `TestPointList` layers.
- **`Reports/`**: ERC and DRC reports. **Only generated on `CHECKED` and
  `RELEASED`.** `DRAFT` and `PRELIMINARY` explicitly skip both checks
  (that's the actual difference between `PRELIMINARY` and `CHECKED`: same
  documents, but `CHECKED` additionally runs and enforces ERC/DRC, failing
  the build on errors).
- **Impedance table** (Tier 2, opt-in): an extra CSV + PDF section for
  boards with controlled-impedance traces, enabled per-board via
  `configure.py`'s Tier 2 prompt.

**Where it all ends up:** every one of these gets committed straight back to
the branch that triggered the run (`dev`/`main` directly, or `main` via the
release job for a tag push). Nothing above is gitignored; a fresh clone
just won't have these folders until the first CI run creates them.

**Every run starts by deleting the previous outputs**
(`Manufacturing/`, `Schematic/`, `3D/`, `Testing/`, `Reports/`, and the
generated PNGs in `Images/`) before regenerating them, so a file that stops
being current (e.g. a drill table for a via that no longer exists) never
lingers and gets silently re-committed as if it were still accurate.

### Running KiBot locally (maintainer-only)

**Regular members never install KiBot locally; CI generates everything.**
This is a maintainer-only escape hatch for debugging a KiBot config change
before pushing, or validating a fix before trusting CI with it. Requires
Docker Desktop installed and running. `kibot_launch.sh` calls the `kibot`
command, which only exists *inside* the Docker image. Run it through
Docker, not directly on your host machine:

```
docker run --rm -v "<path-to-this-repo>:/workspace" -w /workspace \
  ghcr.io/inti-cmnb/kicad10_auto_full:dev bash kibot_launch.sh -v DRAFT
```

(Windows example: `-v "C:\Users\you\Git\<board>:/workspace"`.) Swap
`-v DRAFT` for `-v CHECKED` / `-v PRELIMINARY` / `-v RELEASED`.
`kibot_launch.sh` deliberately mirrors `ci.yaml`'s variant logic exactly, so
a clean local run is a real predictor of what CI will do. Omit `-v` and it
defaults to `CHECKED`. `docker run ... bash kibot_launch.sh --help` lists
every option.

The first run pulls a multi-gigabyte image; expect that to take a few
minutes.

KiBot's preflights can leave incidental changes in the actual design files
(`.kicad_pcb`/`.kicad_pro`/`.kicad_prl`) as a side effect of generating
documentation. These are safe to discard (`git checkout -- <file>`), not
real design changes. This is exactly what `ci.yaml`'s own "discard changes
to source project files" step cleans up on every CI run too.

**KiCost** (local board cost estimation, run manually to avoid burning API
quota in CI): copy `kibot_yaml/kicost_config_local_template.yaml` to
`kibot_yaml/kicost_config_local.yaml`, fill in your distributor API keys,
then `./kibot_launch.sh --costs`. Produces a spreadsheet in
`Manufacturing/Assembly/`.

### Credits & Resources

- [@set-soft](https://github.com/set-soft) for [KiBot](https://github.com/INTI-CMNB/KiBot),
  see the [KiBot documentation](https://kibot.readthedocs.io/en/latest/).
- [krishna-swaroop](https://github.com/krishna-swaroop/KiCAD-Prism) for Prism.
- [nguyen-v/KDT_Hierarchical_KiBot](https://github.com/nguyen-v/KDT_Hierarchical_KiBot),
  the base this template is adapted from.
- [KiCost](https://github.com/hildogjr/KiCost) for local cost estimation.
- [KiCad Library Convention](https://klc.kicad.org) and
  [kicad-library-utils](https://github.com/kicad/kicad-library-utils) for
  the symbol/footprint rules Prism checks submissions against.

### Known open items

Flagged rather than assumed:
- Exact menu wording for installing Prism's Remote Symbol Provider package
  and adding the provider link can vary between KiCad point releases; the
  steps in [section 2.4](#24-connect-kicad-to-prism-and-log-in) are correct
  in shape but worth a quick sanity check against whatever KiCad 10 point
  release you're actually running.
- Whether footprints/3D models come through that same channel.
- Prism's actual catalog field names for Manufacturer/MPN (`kibot_main.yaml`
  uses placeholders pending verification).
- Who on the team actually holds Prism's `designer` role (able to create
  and submit new components) versus who only requests parts via the `LIB`
  commit type; not written down anywhere yet.
