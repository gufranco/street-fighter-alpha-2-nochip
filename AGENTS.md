# Working in this repository

Read [`FAMILY.md`](FAMILY.md) first. It is the standard every member is built to
and it is identical in all twenty of them. This file is the part that is only
true here.

## What this project is, in one paragraph

Street Fighter Alpha 2 shipped with a decompression chip on the cartridge, and
without that chip the game does not run. This produces an image that does not
need it: every stream the S-DD1 would have expanded at runtime is expanded ahead
of time, and what is left is refitted into a windowed map that a plain 96 Mbit
cartridge can hold. Around that sit corrections to the game's own code and a
faster sample upload, both of which change instructions that run on real
hardware.

## The nine models, and why there are nine

Every claim about what a part does is made by a member on the import path, never
here. [`hardware.py`](hardware.py) is the only way any of them is reached, and it
is where a missing checkout is explained rather than left as an import error.

| Model | What it answers |
|:--|:--|
| `sdd1` | What the decompressor produces for a given stream |
| `mos65xx` | What the cartridge's own code does when run |
| `spc700` | What the audio processor does |
| `ssmp` | The same, with the mixer and boot program behind it, and cycles |
| `sdsp` | What reaches the mixer |
| `mapper` | Where an address lands in a cartridge |
| `romimage` | What a header says and what its checksum should be |
| `snesgfx` | Whether a decompressed stream reads as tiles |
| `snesdriver` | Where in the code the cartridge talks to its chip |

Nine is not thoroughness for its own sake. A patch to code that runs on hardware
is checked against a model held to its own suite, rather than against this
project's expectations. When two models can answer the same question, ask both:
the sample upload runs on a stand-in written from a reading of the driver and on
the whole audio unit, and the two agreeing is the check that neither provides
alone.

## The authority ladder applies, and rung four is the one to watch

The ladder is in [`FAMILY.md`](FAMILY.md). What is specific here is how much
material sits on the bottom rung. This game has been patched by many people, and
those patches come with changelogs, assembly and claims.

**A third party patch is never evidence.** Not about hardware, and not about
itself. One widely circulated package ships assembly describing a two byte
upload and a binary whose driver reads three ports per handshake; they are
eighteen months apart and describe different drivers. Anything taken from such a
package is re-derived here and measured, or it is not taken.

## What is settled and what is not

[`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md) is the list, and
[`conformance/divergences.json`](conformance/divergences.json) is the same list
in a form a program reads. The two must agree. The short version: the Japanese
stream table is converged rather than proved complete, and two corrections are
read from the disassembly rather than seen on screen.

## The order matters

Streams are found, decompressed, verified, and only then packed. A stream that
fails to decompress is a missing entry in a table, not a broken decompressor, and
the tools say which. Packing before verifying produces an image that boots and is
wrong somewhere nobody looked.

## The input is a retail cartridge, and it is not here

Neither image is in this repository and neither is any output. Everything
published is a digest, and [`artifacts.manifest.json`](artifacts.manifest.json)
carries four per artifact so a reader can confirm what they have without being
handed any of it. `sha256` is what decides; the other three are for
cross-referencing against public databases.

Nothing in `roms/`, `boot/`, or any `*.sfc`, `*.smc` or `*.bin` may be committed,
in any form, for any reason. [`.gitignore`](.gitignore) enforces the common
cases and is not the reason: the reason is that this project does not
redistribute what it did not write.

## Every gate, in the order to run them

```sh
uvx ruff@0.16.3 check .
uvx ruff@0.16.3 format --check .
pnpm run format:check
for module in *.test.py tools/*.test.py; do python3 "$module" || break; done
```

The ruff version is pinned because a local install of a different version
disagrees, and a report from a version nobody ships is worse than no report. The
suite takes several minutes and 755 tests; a run that finishes faster than that
did not run all of it.

`pnpm`, never `npm`. The JSON and YAML formatter is a separate gate from ruff and
CI runs both, so a run that passes ruff alone has not passed lint.

## Conventions that are not negotiable

- Python only. No comments in source; reasoning goes in docstrings.
- Tests are `<module>.test.py`. Arrange, blank line, one act, blank line, assert.
  No section labels and nothing inside a test body explaining itself.
- A check nobody has seen fail is not known to work. Drive every new check
  against input that should fail it before keeping it.
- A digest edited to make a check pass is the failure this whole standard exists
  to prevent.
- Conventional Commits, subject under 50 characters.

## Things that will bite you

**A docstring claiming a measurement is not a measurement.** One here said the
audio unit's boot window had to be hidden or the driver ran away. Running it both
ways showed the window changes nothing. Read what the test actually exercises
before believing what the prose asserts.

**The models start unclean.** Registers and memory hold arbitrary but
reproducible values, because hardware does. Anything relying on a register being
zero without setting it was relying on the model being tidier than the machine.

**The audio ports are two sets of latches, not one.** The driver cannot read its
own acknowledgement and the console cannot read what it wrote. A harness that
models them as one location will appear to work and will measure the wrong thing.

**The counter the console offers first is compared, not echoed.** Hand the driver
a value it did not expect and it takes the other side of a branch two
instructions in and never returns.

## Before calling anything finished

Every gate above, green, in this session. Then: does any new claim in a docstring
correspond to something a test actually drives, and has that test been seen to
fail? If a question was closed, is it closed in both
[`OPEN-QUESTIONS.md`](OPEN-QUESTIONS.md) and
[`conformance/divergences.json`](conformance/divergences.json)?

## What a change is expected to leave behind

A measurement rather than an assertion. If the change is about speed, cycles from
the audio unit rather than instruction counts. If it is about what a stream
contains, a digest. If it closed a question, the question moved rather than
disappeared, and if it corrected an earlier wrong answer, the earlier answer is
still visible with what replaced it.
