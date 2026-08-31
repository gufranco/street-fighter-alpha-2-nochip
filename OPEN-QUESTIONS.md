# Open questions

What this project does not know for certain, and what it would take to find out.

This member makes fewer claims about hardware than its size suggests. It
decompresses streams ahead of time, refits what is left into a map with no
coprocessor in it, and patches code. Every statement about what a part actually
does is made by one of the nine members on its import path, each held to its own
suite. So most of what could go wrong here is not a question about silicon. It is
a question about coverage: whether the streams found are all the streams, and
whether a correction that reads right has ever been seen to matter.

Every entry below is also in
[`conformance/divergences.json`](conformance/divergences.json) with its status
and severity, so a program can read what a person reads here.

## The Japanese stream table cannot be proved complete

A stream nobody asks for cannot be found by asking. The table was built by
driving the Japanese cartridge and recording all 1,661 requests it made, and the
search converged, meaning further driving stopped finding anything new. That is
the strongest statement available and it is not a proof.

The USA table does not have this problem. It came out of an image that tags where
each stream begins, so it was read rather than discovered, and the two methods
agreeing on the streams they share is what makes the Japanese one credible.

If a screen ever comes up wrong, the fix is mechanical rather than exploratory:
drive the retail cartridge to that screen, read what it asks the chip for, add
it. Nothing about the approach has to change.

**What would settle it:** a tagged Japanese image, or a run that reaches every
screen in the game.

## Two corrections are not demonstrated on screen

The object table overflow needs eight simultaneous shadow frames and a projectile
collision in the same instant. The thrown father sprite sits in a scene no run
here reaches. Both corrections rest on reading the disassembly.

What the runs do show is that neither changes anything that is reached, which
bounds the risk without demonstrating the benefit. That is a weaker claim than
the rest of this project makes, and it is written down rather than rounded up.

**What would settle it:** a recorded input sequence that reaches either scene,
run before and after.

## What the prototype settled, and what it did not

Capcom shipped a prototype of the Japanese cartridge dated 1996-09-15. It
declares no coprocessor and stores uncompressed a large amount of what the retail
cartridge compresses.

Decompressing every stream in the Japanese table and searching that prototype
finds **242 matching in full, 311,264 bytes**, with no partial match counted.
Those bytes are Capcom's own data from before the compression step, so for those
entries the table is not merely converged, it is confirmed against the source.

That is a correctness result and not a completeness one, and the two are kept
apart deliberately. A stream missing from the table is still missing from it, and
the prototype cannot reveal one, because it is a different build: 2,138 of the
table's streams are absent from it and 472 share only a first sixty four bytes.
The section above stands unchanged.

## What is closed, and why it is worth saying

**The boot window does not reach the upload driver.** An earlier reading here
said the audio driver ran away when the unit's boot program was left covering the
top of memory. Running it both ways reaches the same bytes in the same cycles,
because this driver never reads what the window covers. The window is still
switched off, because that is the state a console leaves it in, and a test keeps
the measurement so that a patch which does reach up there shows a difference
instead of hiding one.

It is listed because the wrong version of it was written down first, and a
correction that leaves no trace teaches nobody.

## Boundaries, so nobody mistakes them for gaps

**Nothing here models hardware.** The nine members do. The one thing this
measures directly is how many cycles a patched driver spends, and it measures
that by running the driver on the audio unit rather than by counting from a
table. That distinction is the reason the unit is on the import path at all.

**A published patch is not evidence, including about itself.** A widely
circulated third party package ships assembly dated 2021-03-08 that describes a
two byte upload, and a binary dated 2022-10-21 whose audio driver reads three
ports per handshake and self modifies its destinations. The two describe
different drivers, and the changelog entry naming two bytes predates both.
Nothing here is derived from either. The mismatch is recorded so that no later
reader treats the published assembly as a description of the shipped binary.

The same gap closes off its later work entirely. That package advertises fixes
for a double KO hang, a freeze when facing Zangief and a black screen crash,
dated 2021-06-14, 2021-06-21 and 2022-10-13, all after its published assembly and
none present in it. Subtracting every address that assembly touches from the
binary diff leaves 641 unexplained runs and 39,643 bytes, unlabelled, and the
same diff adds 64 long calls into bank `$C7` and 39 into bank `$D2`, whose
mapping depends on the very S-DD1 window this project removes. The three fixes
are therefore neither identifiable nor addressable here, and no run here reaches
a double KO to demonstrate one if they were. They are wanted and they are out of
reach, which is a different thing from being ignored.

**Neither cartridge is here, and neither is any output.** Everything published is
a digest. That is a rule rather than a limitation, and it is the reason the
manifest identifies inputs by four digests each: a reader can confirm they have
the right file without being handed any part of it.
