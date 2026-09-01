# The family standard

One standard, carried identically by every repository in the family. It is not a
style guide. It is the set of decisions that were expensive to reach, so that a
repository starting today does not have to reach them again and a repository
already running does not drift away from them quietly.

The family is eighteen repositories. Where they differ from each other, the
difference is something the hardware forces rather than something nobody got
round to.

| Member | What it models | Kind |
|:--|:--|:--|
| [mos65xx-python](https://github.com/gufranco/mos65xx-python) | The 65xx family: sixteen parts, from the 6502 to the 65816 | Clocked part |
| [zilog-z80-python](https://github.com/gufranco/zilog-z80-python) | The Z80: three parts, NMOS and CMOS | Clocked part |
| [nec-upd7725-96050-python](https://github.com/gufranco/nec-upd7725-96050-python) | The NEC uPD7725 and uPD96050 digital signal processors | Clocked part |
| [sony-spc700-python](https://github.com/gufranco/sony-spc700-python) | The SPC700, the processor inside the audio unit | Clocked part |
| [arm6-python](https://github.com/gufranco/arm6-python) | The ARM6: a 32 bit processor, and the one part of its family whose bus is documented | Clocked part |
| [snes-obc1-python](https://github.com/gufranco/snes-obc1-python) | The OBC1 sprite remapper | Part |
| [snes-rtc-python](https://github.com/gufranco/snes-rtc-python) | The two real-time clocks a cartridge could carry | Part |
| [sony-s-dsp-python](https://github.com/gufranco/sony-s-dsp-python) | The S-DSP: eight voices on a thirty two step clock schedule | Part |
| [snes-dsp-python](https://github.com/gufranco/snes-dsp-python) | The DSP-1 through DSP-4, the uPD77C25 as Nintendo shipped it | Part |
| [snes-st-python](https://github.com/gufranco/snes-st-python) | The ST010 and ST011, the two coprocessors Seta made | Part |
| [snes-sdd1-python](https://github.com/gufranco/snes-sdd1-python) | The S-DD1's arithmetic decompressor | Part |
| [snes-spc7110-python](https://github.com/gufranco/snes-spc7110-python) | The SPC7110's decompressor, all three of its modes | Part |
| [sony-s-smp-python](https://github.com/gufranco/sony-s-smp-python) | The S-SMP: the processor, the sound generator and the boot program between them | Board |
| [snes-mapper-python](https://github.com/gufranco/snes-mapper-python) | The cartridge memory map and its transfer engine | Board |
| [snes-graphics-python](https://github.com/gufranco/snes-graphics-python) | The graphics formats: tiles, palettes, tilemaps, sprites and mode 7 | Format |
| [snes-rom-image-python](https://github.com/gufranco/snes-rom-image-python) | The forms a cartridge image is stored and shipped in | Format |
| [snes-driver-python](https://github.com/gufranco/snes-driver-python) | What a cartridge says to its coprocessor, read out of the cartridge's own code | Tool |
| [snes-dungeon-master-nochip](https://github.com/gufranco/snes-dungeon-master-nochip) | Dungeon Master with its graphics coprocessor designed out | Tool |
| [snes-star-ocean-nochip-fix](https://github.com/gufranco/snes-star-ocean-nochip-fix) | A header correction for two rebuilt images | Tool |
| [snes-street-fighter-alpha-2-nochip](https://github.com/gufranco/snes-street-fighter-alpha-2-nochip) | Street Fighter Alpha 2 with its decompression chip designed out | Tool |

The kind decides which parts of this file apply. A clocked part answers to all of
it. A part, a board, a format or a tool skips the section about a clock and keeps
everything else, which is most of it: the authority ladder, the record, the
tools, the documents and how it is written do not care whether the thing being
modelled has a clock.

Clocked means running a program, not having a crystal. A clocked part is driven
by a budget of cycles and reports what it spent, which is the interface the
section about a clock describes. A part answers accesses instead: a chip that
remaps an address, or one that hands back a time, is asked a question and
answers it, and has no instruction to step through and no cycle count to hand
back. A real-time clock ticks and is still not a clocked part, because nothing a
host does to it is measured in cycles. Naming those two the same thing would ask
one of them for a `step` it has no meaning for, and a stub is an invented
interface rather than a kept promise.

Nothing else is a member. A copy of this file sitting in a repository outside
that list is a working note somebody left there; it binds nothing and it is not
expected to match. Membership is a decision, not something a repository acquires
by holding a copy.

## How a repository joins

Copy this file in unchanged, follow it, and add the repository to the table
above in every member in the same task. The published copies live in the three
repositories listed there and are byte-identical to each other, so any copy can
be checked against any other:

```bash
WORK=$(mktemp -d)
git clone --depth=1 https://github.com/gufranco/zilog-z80-python.git "$WORK/reference"
diff "$WORK/reference/FAMILY.md" FAMILY.md
```

Everything above the repository's own closing section is shared and must match
across the members. A rule that needs changing is changed in every member in the
same task. A copy that has drifted is worse than no copy, because a reader trusts
it.

### What a new repository has to have before it is a member

Each line below was a defect found in one of the existing members and fixed in
all of them. A repository joining now starts with them rather than earning them
one session at a time. Every one is checkable, and `conformance/family.test.py`
checks the ones a test can reach.

**The interface**

- [ ] `Cpu(model, memory)` builds the part, keeps what it is handed, and builds
      its own when the argument is left out.
- [ ] On a **Part**, `Chip(model, store)` does the same job under the name that
      kind has. What it hands back is a class called `Chip`. A part that executes
      nothing should not be built by something called `Cpu`.
- [ ] A part that comes up holding whatever it held offers `reset()`, and what
      that reset does is either quoted from a document or recorded as not stated,
      with the measurement that would settle it. A reset nobody can account for
      is an invented pin.
- [ ] A part publishes its catalogue even when it holds one model: `MODELS`,
      `Model` and `UnknownModelError`. There is no default model and nothing that
      hands back a description of a part instead of a part. A name no model goes
      by is refused, and naming none is refused too, with every model there is
      listed in the refusal.
- [ ] What it hands back is a class called `Cpu`, not something else. The name
      shows in every repr and every traceback.
- [ ] `step`, `run_for`, `run_until`, `reset`, `held` and the counters exist and
      return what the standard says they return.
- [ ] Every class the package publishes declares `__slots__`. Without them a name
      the class does not have is accepted in silence, the one meant keeps its
      value, and nothing reports that the write went nowhere.
- [ ] No unslotted class anywhere in a chain, which would hand the dictionary
      back to every subclass below it.

**Errors**

- [ ] One `errors.py`, holding everything the package raises, importing nothing
      from the package so it can never close a cycle. Both halves are checked.
      A cycle that breaks outright announces itself, and the one worth a check is
      the import that works today because of the order modules happen to load in.
- [ ] No exception defined twice under one name. Two classes under one name both
      work, both get tested, and `except` catches half the cases it names.
- [ ] Every exception a caller can meet is exported from the package. `except`
      takes a name, and one that cannot be imported can only be handled by
      catching everything. A leading underscore is how an internal one says so.
- [ ] `__all__` lists names, never modules. A submodule is reachable whether or
      not it is listed, because importing a name out of one makes it an
      attribute of the package, so listing it changes nothing except what
      `import *` binds while presenting the arrangement of the code as part of
      the interface. Modules that a caller reaches for are re-exported with the
      redundant alias a type checker reads as deliberate, `from . import core as
      core`, which keeps the attribute without publishing it.

**The record**

- [ ] An `authority` block in the record, naming the rungs this member actually
      reaches, in order, and why that is the order. The rungs differ enormously
      between members and a reader cannot tell without being told.
- [ ] `comparedAgainst` in that block, naming what this member is held to
      outside itself and the runner that does the holding. A member compared only
      against itself proves its two halves agree, which they do just as perfectly
      when both are wrong.
- [ ] A `documents` block, each entry naming the file it is, and every citation
      naming one of those keys. Where it points inside goes in `section`.
- [ ] A record that quotes a document ships `conformance/quotes.py` and the
      pipeline runs it. Four members quoted with nothing checking them, one of
      them forty-one sentences deep.
- [ ] Every quote is present in the document it names, not merely in some
      document. Those come apart exactly when a fact is filed under the wrong
      source.
- [ ] A section naming a numbered table names one the document has. The words
      quoted beside it are checked and the table is prose, so a citation can be
      correct in every part a check reads and still send a reader to a table
      only a different sheet has.
- [ ] Every passage taken from a document sits under a key ending in `quote`,
      or `quotes` for a numbered set of them. Those are the only kinds the
      checker reads, so a passage under any other name is a document's words
      that nothing holds to the document, and it drifts the way a comment
      drifts: quietly, while still reading as evidence. Twenty-one were found
      here in one pass under names like `footnote`, `notes` and `pushedBytes`.
- [ ] A second passage beside a first one is its own entry with its own
      document, section and page, never a field named for being second. The
      marker saying the words are the document's but the order is not belongs
      to a single passage and silences every quote on its node, which is how a
      sentence from one manufacturer's sheet sat unchecked under another's.
- [ ] A long run of words that a pinned document carries verbatim is that
      document's, whatever the key is called, and a check says so rather than
      trusting the name.
- [ ] A document covering more than this part declares the file pages that are
      this part's, and every fact citing it names one of them.
- [ ] Every fact names the parts it governs. Left unsaid it is carried by how the
      key is spelled, and a claim read from one part's sheet reads like its
      neighbours.
- [ ] A value that differs between parts is checked against the model rather than
      taken on trust.

**The tools**

- [ ] Everything under `conformance/` runs as `python3 -m conformance.name` and
      imports its siblings through the package. Run as a script, its own
      directory goes on the import path and shadows any standard library module
      of the same name.
- [ ] A `doctor` beside the package, run as `python3 <package>/doctor.py`, on
      every member that reads a file it does not carry. All of them do.
- [ ] The doctor runs on the machine it exists to diagnose. Nothing it needs is
      imported at the top of the file, because the package is one of the things
      that can be broken, and a traceback in place of a report helps nobody.
- [ ] A throughput floor, several times below what the model does, run
      uninstrumented and outside the coverage step.
- [ ] Every worked example in the README is run and its output compared to what
      the README claims.
- [ ] Every required field in an issue form is actually required. `validations`
      indented one level too far is ignored in silence.
- [ ] The test count the README advertises is the count there is.
- [ ] A pinned corpus names a repository somebody can still push to. One pinned
      here named a repository that had been archived and subdivided, so the job
      watching it for corrections was watching something nobody could correct.
      A correction had landed in the set's own repository fourteen months
      earlier, and this model disagreed with five of the six files it touched.
- [ ] The record says where a corpus comes from, not only which commit it is at.
      A recording generated by an implementation and a capture from a part are
      different kinds of evidence, and a reader who cannot tell which one they
      have cannot weigh it.
- [ ] Every figure the readme advertises is held to something. A count that can
      be derived from the record is checked against it, so the claim cannot
      outlive a change to the pins. A count that can only be measured says so,
      beside the command that measures it. One member advertised a number that
      appeared in no other file at all.

**The documents**

- [ ] `README.md`, `AGENTS.md`, `CLAUDE.md` pointing at it, `FAMILY.md`
      identical above the marker at the end of its shared part, and
      `OPEN-QUESTIONS.md`.
- [ ] `AGENTS.md` carries the same ten sections under the same names in the same
      order. Anything a member adds about its own part sits between what is
      settled and the gates, so the shared spine reads the same everywhere.
- [ ] The number of open questions it claims is the number the file holds. Two
      of the three said a figure that had stopped being true, one by six.
- [ ] No mention of any system the part was used in, in any tracked file, when
      the part existed independently of any system. A processor sold as a
      component is not the machine somebody put it in, and a package that names
      one is a catalogue of that machine's parts wearing a processor's name.
      Identify a variant by its part number, never by the box it shipped in.
      Whatever drives the part is the `host`, whichever kind of machine it was.
- [ ] The rule above is about parts that outlived their first customer. A member
      that models something which only ever existed as part of one machine, a
      cartridge memory map, an image format, a board, names that machine because
      that is what it models, and there is no more general thing to name instead.
      The test is whether the part could be bought and designed into something
      else. A Z80 could. A cartridge bus could not. Each member writes the answer
      out rather than leaving it to an empty list of names, because a list nobody
      filled in and a list with nothing to say look identical.
- [ ] Two things are outside that and each says something. A quoted passage is a
      document's words, and a document may name whatever it likes. The file
      declaring the names to search for is the list rather than a mention.
- [ ] Nothing licensed to anybody else is carried, fetched, vendored or
      generated. A copy belongs on the machine that runs it. Checked two ways:
      no tracked file carries a document or image extension, and nothing is
      tracked from the folder those live in.
- [ ] The repository's own ignore file covers every ignorable path on its own.
      One configured on a machine does not travel with a clone, so a path
      protected only there is exposed in every other checkout and in CI, and
      nothing shows locally because the status a person reads has that file
      applied. Reading it with that file switched off is the check.

**How it is written**

- [ ] The readme carries the same seven sections under the same names in the
      same order, whatever the member models: install, the interface, is it
      right, working on it, references, citing this, license. A clocked part
      carries five more between the interface and the evidence, about pacing it
      against a real clock, driving it a cycle at a time, its models, reading a
      program without running it, and why nothing starts clean. Anything else a
      member adds sits in that same middle, so the spine reads the same
      everywhere. A reader who learned where something lives in one member finds
      it in the same place in the next, which is most of what a shared shape buys.
- [ ] It opens with a line of numbers somebody ran, before any prose: what was
      compared, how much of it failed, the test count, the coverage, and what it
      costs to install. A count of what was compared with no result beside it is
      half a claim.
- [ ] No comment in any source file that no tool reads. Reasoning goes in the
      docstring, where it sits with the thing it explains and is read by anyone
      who asks for help on it. A comment is the one part of a file nothing checks,
      so it is the one part free to drift, and once it has drifted it misleads
      every later reader rather than merely failing to help.
- [ ] `noqa`, `type:`, `ruff:` and the rest stay, because a tool parses them and
      reports them when they go stale. Nothing else does.
- [ ] Every test is named as a sentence about behaviour, continuing the one its
      class began. `test_step` names the function that was called, which a failure
      message already told you.
- [ ] The checkers are set the same way: strict types, a hundred percent floor on
      statements and branches, one line length. A member that grades itself more
      gently is not held to the standard, it is exempt from it.

### When a member depends on another member

Four members do. A driver needs a memory map to know which address a write
lands on; an image format needs one to know where a header sits; a header fix
needs the image format. That is the hardware's shape, not a failure to keep
things separate, and the dependency runs one way in every case.

The dependency is a git submodule on the import path, never a published package:

```yaml
env:
  PYTHONPATH: .:snes-mapper-python
```

```bash
git clone --recurse-submodules https://github.com/gufranco/<member>.git
```

That choice has a price and the price is paid deliberately rather than
discovered later:

- **A source archive cannot carry a submodule.** The download-zip link on the
  repository page produces a checkout that cannot run. Say so in the readme, at
  the install step, rather than letting somebody find out.
- **The member is not installable from an index** while it consumes another this
  way, so it carries no `[project]` block and publishes nothing. A member that
  wants to be installable takes the dependency as a version range instead and
  says which.
- **A submodule pins a commit, and a pin can go stale exactly as a corpus pin
  can.** The same rule applies: the repository it names must still be one
  somebody can push to, and the pin is checked against its head rather than
  assumed current. It is not enough to be checkable. Every member consuming
  another tracks its head, the weekly job reports how far behind each pin has
  fallen, and a pin is moved because the report says so rather than because
  somebody happened to look.

  One pin was a hundred and twenty four commits behind when this was written,
  so a member was reading a cartridge's code with a processor model carrying a
  defect fixed that morning. Another was eight behind, and moving it changed
  the bytes a tool writes, because one of those commits corrected a checksum
  for images whose length is not a power of two. Both were found by asking
  rather than by anything failing.

- **Moving a pin is a change to this member's behaviour until proven otherwise.**
  Run the suite against the newer copy before committing the bump, and when the
  output changes, find out which upstream commit changed it and why before
  touching anything that records what the output should be. A digest updated to
  make a check pass is the failure this whole standard exists to prevent.

What must not happen is a module-level import of a sibling with nothing
declaring it. That is how a package looks installable, is not, and fails at
import time on the first machine that is not the author's.

Most of this applies to anything that models hardware: a processor, a coprocessor,
a mapper, a ROM image format, a peripheral. One section is explicitly about parts
driven by a clock, and a repository that models something else skips it and keeps
the rest.

## The rule above every other rule

**Fidelity wins every decision.** Not most of them, and not the ones where the
cost is small. Every one.

When fidelity pulls against speed, against a nicer interface, against a smaller
diff, against a simpler implementation, against a shorter test run, against
finishing today: fidelity wins, the cost is paid, and the cost is reported rather
than negotiated. Everything below this line is an application of it, and any rule
below that appears to conflict with it is being read wrongly.

Two consequences come up constantly, so they are written down rather than
rediscovered:

- **A shortcut that is invisible in tests is still wrong.** Nothing in a suite
  fails when a discarded read is skipped, or an instruction runs in one step
  instead of the cycles it takes, or a field nobody reads is left unparsed. That
  is what makes the trade tempting and what makes it damaging.
- **Slower is an acceptable outcome. Less accurate never is.** A performance
  problem is fixable afterwards by anyone. An accuracy shortcut has to be undone
  by doing the work a second time, and until it is, every result built on it is
  suspect.

## The authority ladder

Every factual question is answered by the highest rung that has an answer, and a
lower rung never overrules a higher one.

1. **Manufacturer documentation.** Read page by page, not searched for keywords.
   Every document is listed in the README's References section with its page
   count and digest, and every fact taken from one is recorded with the sentence
   it came from and the page it was on.
2. **The artifact itself.** A measurement on real hardware, or the bytes of a
   real dump. Strongest available evidence about the thing rather than about a
   description of it.
3. **A simulation of the die itself.** A netlist read off die photographs and
   stepped a half cycle at a time is not a model of the behaviour: nobody wrote
   down what it should do, so it cannot carry somebody's reading of a manual. It
   answers what a data sheet drawn at cycle resolution cannot, which is what the
   part drives during a cycle it spends thinking. Below the artifact because it
   is one die and a photograph of it, above any recording because a recording
   says only what its author chose to write down.
4. **A recording from an independent implementation.** A pinned conformance
   corpus, a reference dump, a published trace. Strong, and still evidence about
   the program that produced it rather than about the hardware.
5. **Anything else.** Another emulator, a community write-up, a primer. Reached
   for only when every rung above is silent, cited as what it is, and never left
   as the sole support for a fact a manufacturer would have printed. A source
   with no measurement behind it is not cited at all.

Which rungs a member reaches differs enormously, so each record names its own
in an `authority` block rather than leaving a reader to infer them. One member
holds every claim to 2,781 retail cartridges, which is rung 2. One compares
against a simulation of the die, which is rung 3. One models a chip for which no
document is known to exist and says so. Nine stated their ladder and one did not,
and nothing noticed, which left a reader of that record unable to tell a figure
quoted from a manufacturer from a figure somebody found convenient.

**Every member is held to something it does not own.** Four are measured against
real cartridges or real images. Three are compared against a suite recorded from
an independent implementation, one of those also against a simulation of the die.
Three are compared against an independent implementation built from a pinned
commit. Which one is named in `comparedAgainst`, with the runner that does it.

That line exists because one member had nothing. It walked its whole input space
and proved its decoder and its encoder agreed, and a decoder and an encoder wrong
in exactly opposite ways agree perfectly: swapping two bits in the record and in
the code together passed every gate it had. A round trip is evidence about
self-consistency. It is not evidence about the figure it was read from.

When two rungs disagree and the ones above them are silent, the answer is
**unknown**. It goes in `conformance/divergences.json` with the measurement that
would close it, and from there into `OPEN-QUESTIONS.md`. Picking the more
convenient source and moving on is the one thing no repository here does.

**An implementation is a lead, never an authority.** Two projects that share a
lineage agreeing is one source, not two.

## What that rule looks like in practice

The purpose is a model of the hardware, not something pleasant to use or quick to
run that resembles it.

- **Nothing starts cleared.** Memory, registers and buffers hold a reproducible
  scrambled pattern. There is no parameter that zeroes them and there will not be
  one: a read of a byte nothing wrote is a defect on real hardware, and storage
  that answers zero turns that defect into a passing test.
- **Bugs are features.** A part's defects are modelled, not corrected. A model
  that quietly fixes a hardware bug is wrong for the machine that shipped it.
- **Revisions are separate parts.** Including the ones that only fixed a bug.
- **Undefined is a value, not an absence.** Where the hardware leaves something
  undefined, say so and make it reproducible from a seed. Never substitute a
  convenient default and never document one as if the hardware chose it.
- **A discarded read is a real access.** Anything the hardware puts on a bus, or
  writes to a file, the model does too, including what exists only as a side
  effect.

## Modelling a part driven by a clock

Skip this section if the repository models something that is not clocked.

A part runs at whatever its crystal says. A model that runs as fast as the host
manages is an emulator, so it reports what it spent and lets a host hold it to a
real frequency.

This is written for a part driven by a clock, and one line of it is not: a part
that answers accesses has no clock and still comes up holding whatever it held,
so it offers `reset()` too. What that reset does has to be accounted for. Three
of these quote a manufacturer for it, including what it costs. One has no
document in existence and records the behaviour as the reference implementation's
with a measurement that would settle it. The two clocks model the console's reset
line reaching a battery-backed part, which touches no counter and is a different
event from the RESET bit one of their manuals documents; that distinction went
unwritten until somebody asked, and both readings now sit in the record.

A reset nobody can account for is an invented pin, and the family does not ship
those any more than it ships an invented flag.

- **Power on scrambles; reset defines.** Two separate events, kept separate.
  Construction puts every register in the state the rail coming up leaves it, the
  program counter included, so a newly built part executes rubbish from a rubbish
  address exactly as the silicon would. `reset()` then sets only what a reset
  actually defines and leaves everything else holding what it held. A core that
  scrambles inside `reset()` has conflated the two.
- **A caller resets the part; the constructor never does.** There is no option to
  arrive reset and none to arrive cleared, because no board offers either. A
  model that resets on the caller's behalf has hidden an event that costs cycles
  and drives pins.
- **A reset costs what the manufacturer says it costs**, and those cycles appear
  in the tally.
- **`step()` returns the cycles that instruction cost.** Not `None`. A host that
  cannot ask what an instruction cost cannot pace anything.
- **`cycles` is cumulative and survives a reset.** A reset returns the part to a
  known state; it does not rewind the clock the board is running on.
- **`run_for()` returns what it really spent, which usually overshoots.** An
  instruction is not divisible. A host carries the overshoot into the next slice
  instead of discarding it, and a long run does not drift.
- **A halted part still costs its host every cycle.** Whatever a part does when
  it stops is what the model does, and none of it raises from `run_for()`,
  because the board's clock has not stopped. `held()` answers whether the part
  has stopped advancing the program.
- **Every cycle passes through one place.** A counter kept in one method and a
  watcher called from another drift the first time somebody adds a cycle to only
  one of them, and nothing catches it. One method spends the cycle, bumps the
  count and calls `on_cycle`, and every path that costs a cycle goes through it,
  including the ones that touch no memory.
- **An input is a line, not an event.** A method that acts now is a convenience;
  the pin is a level the part reads when the documents say it reads it. A request
  raised and withdrawn before that moment is not taken, because that is what a
  device withdrawing its request does. An edge-sensitive line is compared against
  the level last seen rather than tested.
- **`Clock` suspends the part between any two cycles**, so a host can change what
  a read will answer part way through an instruction. An instruction is an
  ordinary call stack and Python cannot suspend one, so the clock runs the part on
  a thread and lets it block where the cycle is spent, which is what ares and
  bsnes do. It is much slower than `step()`, and that is the correct trade: one
  source of truth for the instruction, two ways to drive it, and the accurate one
  is never the one that got dropped.

### One interface across the family

A caller moving between two repositories should not have to relearn anything the
hardware does not force.

```python
cpu = Cpu("z80")  # or Cpu("6502"), Cpu("w65c02"), Cpu("65816"), Cpu("upd96050")
cpu = Cpu("6502", memory)  # memory is optional; without one the part gets its own
cpu.reset()  # returns the part, so the call chains

cpu.step()  # one instruction, returns the cycles it cost
cpu.run_for(cycles)  # a budget of cycles, returns what was actually spent
cpu.run_until(check, limit)  # steps while check(cpu) is false; limit raises RunLimit
cpu.held()  # whether the part has stopped advancing the program

cpu.irq()  # offer a line and act on it now
cpu.nmi()  # the one no flag defends against

cpu.cycles  # cycles since construction, across resets
cpu.steps  # instructions since the last reset
```

Differences are allowed where the parts differ, and nowhere else. The Z80 takes a
vector on `irq()` and has a separate `Ports` space; the 65816 has `abort()` and a
bank register. Every other name matches, including parameter names. A T state is
the Z80's cycle, so the budget is called `cycles` on all four rather than being
named for one part.

Interrupt lines are the clearest case, and they are declared rather than assumed.
A part publishes one method per line it has, and the lines it has are named per
member in `conformance/family.test.py` as `INTERRUPT_LINES`. Three shapes exist
and each is what the silicon has: a Z80 and a 6502 have a maskable line and a
line above it, the uPD7725 has a single pin and nothing above it, and the SPC700
as Sony shipped it brings none out at all. Requiring all three to publish `nmi()`
would require two of them to publish a stub, and a stub pretends to a pin the
package does not bring out.

Declaring the list away is not free. A member that names no line has to account
for that in its record, where every other fact about the part already is, so
emptying the tuple to skip a check costs the same as printing the claim.

Memory is one of those differences, and the second parameter is not. Every core
takes what it runs on as `Cpu(model, memory)`, keeps the one it is handed, and
builds its own when the argument is left out. What that argument is differs
because the parts do: the Z80 and the 65xx have one flat byte addressed space and
call it `cpu.memory`, and the uPD7725 has three separate stores at three widths,
reached by three different registers, so it has `cpu.stores` with `program`,
`table` and `scratch` inside. One attribute called `memory` on that part would
not answer which of the three a caller meant. A check that needs the store finds
it by shape rather than by either name, because one keyed to the first reports
the other as missing something it deliberately does not have.

`Cpu(model, fill=0)` is the one way across the family to ask for a store holding
one byte everywhere. The default is never that: a store comes up scrambled,
because a read of a byte nothing wrote is a defect on real silicon and memory
that answers zero to it turns that defect into a passing test. What `fill` is for
is a run that has to get through a few dozen instructions without meeting an
opcode that stops the part, which is what every check of a cycle budget needs and
what scrambled memory cannot give. Three of the four members needed a different
keyword for the same request, so a check written against any one of them reported
the other three as broken.

## A doctor for what the repository does not carry

Every member reads at least one file it does not ship: a cartridge library, a
conformance suite fetched into a cache, a submodule, a corpus beside the package.
None of them can be committed, so every one of them is absent on somebody's
machine, and the checks that need them skip.

A skip and a pass print the same thing. That is the whole reason this exists.
A reader who fetched nothing gets a green run and reads it as confirmation, when
what it confirms is that the suite ran over what was there, which was nothing.

So each member carries a `doctor`. It looks at this machine, prints what it
found, and returns non-zero when something is wrong. Its report is meant to be
pasted into an issue exactly as it comes out.

Two rules shape it. Nothing is hidden: a check that fails says what it saw, and a
check that itself throws is caught and reported as what it threw, named by type.
Nothing is inferred: every line is something looked at just now, which is why
each doctor drives the part rather than importing it and calling that a pass.

An absent file is reported as absent, never as a failure. A fresh checkout has no
cartridges and that is the normal state. What is never reported is nothing at
all, and the sharpest line in most of these reports is the one that separates a
directory holding nothing from a directory that is not there. The first reads as
a library to anything that only checks the path, and a run over it passes.

**A doctor that cannot run is not a doctor.** Four of these packages import a
submodule by name, so on the machine the doctor exists for, a checkout without
`--recurse-submodules`, importing the package fails before a single line is
printed and the reader gets a traceback naming a module they have never heard of.
Every doctor therefore imports nothing from its own package at the top of the
file, reads its version out of `version.py` rather than importing it, and is run
as `python3 <package>/doctor.py` so the entry point is the same everywhere. Every
import that can fail happens inside the finding that needs it, where its failure
is the report rather than the end of it.

**A check that reads what happens to be on the machine is a check whose result
depends on the machine.** Three of them passed on a developer's disk and reported
success on a runner that measured, compared and diagnosed nothing: a doctor whose
failure path found images because images were there, and two throughput floors
that measured for real. The failure is invisible by construction, because the
check does not error on the runner, it succeeds having done nothing.

So every check takes what it works from rather than reading it: the images, the
measurement, the reason a member cannot run here. And a member whose part needs a
file it may not ship is verified by reproducing a runner, which is a scratch copy
of what `git ls-files` reports and nothing else.

A worked example in the readme is excused the same way. On a machine without the
file, every example that builds a part refuses, and that refusal is the package
working correctly. `conformance/readme.test.py` reports those as skipped rather
than broken, decided by the member's own `why_not`, which is the same sentence
its doctor prints. A member that publishes none skips nothing.

## One constructor per kind

`Cpu(model, memory)` on a clocked part. `Chip(model, store)` on a part. Same
shape, same argument order, different name, and the name is the kind rather than
the chip.

The order is the point of both. The model is the thing a caller always knows;
what the part runs on is the thing they often do not care about yet, so leaving
it out hands back a part holding what a board holds before anything wrote to it.

The model is not optional and there is no default. A member covering one part is
the tempting exception and the worst one: a caller who learns to leave the model
out there writes the same call against a member covering sixteen and gets a part
nobody picked. Naming none is refused, and the refusal lists every model there
is, so a caller who did not know what to pass learns it from the error rather
than from the source.

Nothing hands back a description of a part instead of a part. An earlier version
of this published `describe(name)`, which read like a test fixture, took two
calls to reach one object, and left a second way to spell a lookup that then had
to be kept working. What a caller wants is the part, and the part carries its own
model.

Two members were reached differently before any of this. One was
`describe(name).build(store)`, two calls for one part, and the other was a class
named for the single chip it modelled and taking no model at all. A caller moving
between three members wrote three different things to do one thing.

So a part publishes a catalogue even holding one entry. It costs a file and it
buys two things: the same call everywhere, and a typo that is refused instead of
silently building something. A constructor that accepts any string and returns
the only part it has is a constructor that cannot report a mistake.

What each kind hands back carries the kind's name, not the chip's. `Chip` shows
in every repr, every traceback and every annotation a caller writes, exactly as
`Cpu` does on the members that run a program. Two clocks with different protocols
are still both `Chip`, because what a reader needs from a traceback is which kind
of thing it was.

## One definition per name

An exception class defined twice under one name is a trap that looks like it
works: `except Stopped` is written against one part, tested against it, and sails
straight through against another. Every shared name has exactly one definition,
in its own module, and every user of it imports that one.

That module is `errors.py`. Everything a package raises lives there, whatever
raises it, and it imports nothing from the package so it can never be the far end
of a cycle. An exception a caller can meet is exported from the package as well,
because `except` takes a name and one that cannot be imported can only be handled
by catching everything. A leading underscore is how a genuinely internal one says
so.

`conformance/family.test.py` holds both halves. It imports every module file in
the package directory rather than the ones the package re-exports, because a
module left out of that list is exactly where a second definition hides.

The same applies to an attribute. Where two parts genuinely need one name for
different things, as `.d` is the decimal flag on a 6502 and the direct page
register on a 65816, the collision is documented in the README with the portable
alternative named beside it. It is never resolved by renaming one part into
something its own documentation does not call it.

## Records are data, not prose

Every hardware fact lives in a JSON record beside the code, with the sentence it
came from and the page it was on. Prose describing the same fact goes stale
silently; a record can be tested against the code, and is.

| File | Holds |
|:--|:--|
| `conformance/hardware.json` | What the manufacturers printed, fact by fact, with the sentence |
| `conformance/divergences.json` | Where sources part, each with a status, a severity, and what would settle it |
| `conformance/links.py` | The weekly check that every cited address still answers |

A document that describes the code is a claim about the code. Hold it to the
code with a test wherever that is possible: a promised interface, a model that
must appear in the README, a count that must match. Where a test cannot reach,
say the claim narrowly enough that it stays true.

Four rules make a citation checkable rather than decorative.

**One vocabulary for naming a document.** Every record declares its sources in a
`documents` block, each with the file it is, and `document` on a fact names one
of those keys. Where the fact sits inside that document goes in `section`. Held
in one field, a key here, a file name there and a prose title with the section
glued on somewhere else, nothing can check any of them: a check written against
keys skips the rest in silence and reports a clean run over the part it
understood.

Where the block sits is arrangement rather than vocabulary. A member whose parts
carry different data sheets declares each part's beside it, which says something
the top of the file could not, and the rule is satisfied as long as there is one
namespace of keys and every citation names one of them.

A member with no document at all declares an **empty** block rather than no
block. Three of these parts have no manufacturer document known to exist, and for
them that absence is the most important thing the record has to say. An empty
block says it; a missing one is indistinguishable from nobody having filled it
in. A source reached through a sibling's record is declared here too, with the
sibling named in `through`, because a digest somebody else read is still a pin
somebody read and a reader has to be able to tell which. Two members cite a
manual neither of them opened: repeating the digest lets a reader confirm they
hold the same scan without leaving the repository, and `through` stops that
repetition from reading as a second reading.

**A quote belongs to the document it names.** Searching every source and keeping
whichever placed it best answers "did somebody publish this sentence", not "did
the one this record cites publish it". Those come apart precisely when a fact is
filed under the wrong source, and then the words are real, the run is green, and
the citation sends a reader somewhere the sentence is not.

**A part's pages, when a document covers several parts.** A data book carries a
dozen chips, and close relatives print the same table under the same name with
the same column headings. The flattened text holds every section at once, so the
search cannot tell them apart. A document that covers more than this part
declares the file pages that are this part's, and a fact citing it names one of
them.

**Every fact names the parts it governs.** Left unsaid it is carried by how the
key is spelled and by which document it cites, and a claim read from one part's
sheet and filed among another's reads exactly like its neighbours. Where a value
differs between parts, the record is checked against the model rather than taken
on trust.

## What every repository carries

| File | Holds |
|:--|:--|
| `README.md` | The document for a person: how to run it, the whole interface, why it can be trusted, and a References section naming every source with its digest |
| `AGENTS.md` | The document for an agent. `CLAUDE.md` points at it so the two cannot drift |
| `FAMILY.md` | This file, identical in every repository |
| `OPEN-QUESTIONS.md` | Every place fidelity is still a claim, and the measurement that would close it |
| `conformance/speed.py` | A throughput floor, so the model cannot get several times slower without a failure |
| `conformance/readme.test.py` | Every worked example in the README, run, with its output compared to what the README claims |
| `CITATION.cff` | How to cite the work, stamped with the released version by the same script that stamps the package |
| `SECURITY.md` | Where to report a security problem, and what counts as one here |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | What a report has to carry to be actionable, with the doctor's output first |

A tool under `conformance/` is run as a module, `python3 -m conformance.name`,
and imports its siblings through the package. Run as a script, its own directory
goes on the import path and a file there shadows any standard library module of
the same name, which is a fault that reads as the code being broken.

The throughput floor sits several times below what the model does, so a shared
runner having a bad minute passes and a real regression does not. It runs
uninstrumented and outside the coverage step, because a coverage tracer costs
about ten times what the model does and a throughput assertion under one measures
the tracer.

The README is for a reader who wants to use the thing. Reasoning about why a
source was believed belongs with the record it reasons about, not in the README.

Three of these were missing somewhere and nothing said so. A readme's "Citing
this" section linked to a `CITATION.cff` that was not there, in three members at
once, under a sentence promising a script kept it in step with the release. The
link rendered, every gate passed, and a reader following it got a 404 on the
project's own front page. A link into this repository is now checked to resolve,
and the table above is the list the check reads.

## Reading a document that is a photograph

Most of these documents are scans of printed books. A scan has two descriptions
of the same page, and neither is trustworthy on its own:

- **The text layer**, if the file carries one. It was produced by somebody else's
  recogniser, years ago, at whatever quality that recogniser managed. The NEC
  data sheet's layer prints `lhe` for `the` and `OP` for `DP`. Searching it for a
  sentence that is plainly on the page returns nothing, and the absence means
  nothing.
- **The page as an image**, read now. This is usually cleaner, and on a table it
  is the only option, because a table is a picture in most of these files. It
  still drops a lone digit, and it misses a faint line outright.

So a figure taken from a document is read **twice**, once each way, and what goes
in the record is what both readings agree on. Where one reading dropped a cell,
the other supplies it. Where neither can, that cell is re-rendered on its own and
read again until two crops agree, and if they never do, the gap is recorded
rather than filled.

### What this costs when it is skipped

Reading one description and trusting it is how the z80 timing table came to name
forty three of its rows after whatever text sat nearest the table, lose rows from
every group page, and omit two instruction groups entirely. Nothing failed. The
numbers were right, the file parsed, and the tests passed for months.

### The traps, in the order they bite

| Trap | What it looks like |
|:--|:--|
| More than one page layout | A page describing one instruction prints three columns; a page describing a group prints four. A parser that assumes one silently reads the wrong column as the name |
| The heading is on the previous page | A continuation page carries the table and names nothing. The nearest text is a running head, and taking it gives a row called `Z80 Instruction Set` |
| A header spelled inconsistently | Two pages of one manual head a column `MCycle` and `M Cycle` where the rest print `M Cycles`. A matcher keyed to the plural walks past both, and two whole instruction groups go missing |
| Homoglyphs | Cyrillic `С` for `C`, `І` for `I`, lowercase `l` for `I`, `O` for `0`. `BІT b, r` looks correct and matches nothing |
| A dropped digit | A lone `1` in a wide column is the single most common loss. Never infer it from the row above |
| Two columns | Reading in `y` order splices the left column into the right mid-sentence, and every quote spanning a line break fails to match |
| Printed number against file position | They differ by the front matter. Record the relationship once, and cite the printed number |

### What the record carries

- The file's **SHA-256**, because two scans of one book paginate differently and
  a page number means nothing without saying which scan.
- The **printed page** beside every quote, and the rule relating it to the
  position in the file.
- **How it was read**, naming both passes, so a later reader knows the reading
  can be repeated rather than having to trust it.

### Column boundaries come from the header

Do not hardcode where a column starts. Find the header row, take each column's
position from the header cell that names it, and assign every cell below to the
nearest one. That is what makes a parser survive a page whose layout differs from
the one it was written against.

### Verifying a quote afterwards

Match on flattened text: strip everything that is not a letter or a digit, and
lowercase it. That survives hyphenation across a line break, collapsed spaces and
inconsistent punctuation. It does not survive a homoglyph or a misread digit, so
a quote that fails to match is a quote to read on the page rather than a quote to
delete.

## Verification

- **100% of statements and branches, enforced.** Not a target.
- **A conformance runner reports a count of what it checked, never a bare pass.**
  A runner that parsed nothing and found no failures exits zero and looks
  identical to one that checked everything, so the count is what separates
  coverage from silence.
- **Nothing is skipped quietly.** Where a comparison genuinely cannot be made,
  it is counted, named and printed, and the reason is written down.
- **Measure before claiming.** Every number in a README is one somebody ran. When
  a claim is checked and found stale, the claim was the defect, not the check.
- **A count is not a comparison.** A model can spend the right number of cycles
  reading the wrong addresses, or produce a file of the right length holding the
  wrong bytes.
- **A check nobody has seen fail is not known to work.** Every check is driven
  against input that should fail it, once, deliberately, before it is trusted.
  This is the rule most often skipped here and the one that has cost the most: a
  duplicate-name check that walked only the modules a package re-exported and so
  could not see the module where a duplicate was sitting; a restructure whose
  script never reached its write and left the check reporting clean because there
  was nothing to check; a path fix that fixed nothing and was believed because the
  run stayed green. Each looked like a pass.
- **Silence and success produce the same output.** A check that found no files, no
  documents, no cases or no records exits zero exactly like one that examined
  everything. Print what was examined, and when the answer is nothing, say that
  rather than nothing at all.
- **A failure path is code.** The branch that reports a fault runs only when there
  is one, so it is the branch least likely to have run. Make the collector take
  its input, hand it something broken in a test, and check what it says.

## Conventions that are not negotiable

| Thing | Rule |
|:------|:-----|
| Language | Python only |
| Dependencies | None at runtime. The standard library is the whole budget |
| Comments | None in source. Docstrings carry the reasoning |
| Test layout | `<module>.test.py` beside the module it covers |
| Test shape | Arrange, blank line, one act, blank line, assert. No section labels |
| Coverage | 100% statements and branches, enforced |
| Types | `mypy` at strict, plus every optional error class |
| Lint and format | `ruff`, clean, no suppressions without a stated reason |
| Variants in the readme | Every model or variant the package accepts is shown being built, with every alias it answers to named beside it. A part nobody can find is a part nobody uses, and the check is for the call rather than the bare name because the call is what a reader came for |
| Commits | Conventional Commits, subject under 50 characters |
| Corpora | Fetched and pinned by commit, never vendored |
| Documents | Read and pinned by digest, never committed: none is redistributable |
| ROMs and dumps | Never committed, in any form, for any reason |

## What "finished" means here

Not that everything is known. That every question which can be answered has been,
and every question that cannot is written down with the measurement that would
answer it.

A repository is finished when `OPEN-QUESTIONS.md` contains only entries whose
closing condition is outside reach: hardware nobody has probed, a document nobody
wrote, or a behaviour the manufacturer never specified. Claiming more than that
is claiming to know things nobody knows.

---

*Everything above this line is identical in every member. A member may add
sections below it about its own state, and nothing may be added above it that
the others do not also get.*

The largest member, and the only one whose output is a cartridge somebody plays.
It takes a game built around a decompression chip and produces one that does not
need it: every stream the S-DD1 would have expanded at runtime is expanded ahead
of time, and what is left is refitted into a windowed map that a plain 96 Mbit
cartridge can hold.

It consumes nine other members as submodules at its own root. The decompressor
is `snes-sdd1`; the map and the image are `snes-mapper` and `snes-rom-image`; the
two processors are `mos65xx` and `sony-spc700`, and the audio unit they talk
through is `sony-s-smp` with `sony-s-dsp` underneath it. `snes-graphics` reads
what came out of the decompressor as tiles, and `snes-driver` reads the
cartridge's own code to find where it talks to the chip in the first place.

Nine models is not thoroughness for its own sake. This member changes code that
runs on real hardware, so the thing every patch here is measured against is a
model held to its own suite rather than to this project's expectations. The
sample upload is the worked example: it runs on a stand-in written from a reading
of the driver and on the whole audio unit, and the two agreeing is the check. The
unit is also the only one that can count cycles, which is what a claim about
transfer speed actually rests on.

Neither cartridge is here and neither is any patched output. Everything published
is a digest. The manifest records what a correct build has, and the streams it
was built from are identified the same way, so a reader can confirm they have the
right input without being handed any of it.
