# Petri-objects

A Petri-object is a named, reusable Petri net that connects to others through
**links** instead of being merged into one flat, overloaded net.

Two kinds of link:

| Link | What it does |
|------|--------------|
| **Place fusion** | One place is repeated by one or more others. Every one of them sees the same tokens |
| **Transition to place** | A transition in one object feeds a place in another |

![Three Petri-objects on one canvas: Generator, Machine and Counter, each a framed net, joined by shared-place links](assets/petri-objects.png)

The point is readability at scale. A large discrete-event model becomes
several smaller nets that each stay understandable on their own, then get
composed, instead of one diagram nobody can follow.

This is the composition technique from
[PetriObjModelPaint](petriobjmodelpaint.md), and the reason this project can
exchange models with it.

## A shared place has a direction

A shared place is a reference rather than a merge. One place is the source, the
place being repeated, and it holds the marking; the others repeat it and show
the same tokens because they are the same place. Drawing the link starts at the
source, and the document says the same thing: each copy is written as a
`<referencePlace>` pointing at the source, which stays an ordinary `<place>`.

One source may be repeated by any number of copies, and a copy may itself be
repeated further, so chains are allowed. Four arrangements are refused, each
for its own reason:

- a place linked to itself;
- the same pair linked twice, or once each way, since one link already states
  the identity and a second says nothing further;
- a place that copies two sources, because then there is no saying which
  marking it holds;
- a chain of links closing into a loop, which the standard forbids for
  reference places too.

Two places of one object may not be linked, since the object would be repeating
itself. Two places belonging to no object may be linked on the canvas, but that
link has no structural form and is left out of both the exported document and
the simulation.

A document is held to the same rules. A file written by hand, by another tool,
or by an older build can declare links no editor would have allowed; those are
dropped on import and reported, and the rest of the document still opens.

## Building them

Three ways, same model underneath:

- **On the canvas.** Objects, links, and the usual editing.
- **From chat.** The agent has its own tools for adding objects, linking them
  by place fusion or a transition-to-place feed, and validating the result, so
  a multi-object model can be built and edited entirely in natural language.
- **Over MCP or the API.** The same tools, driven by another program. See
  [integrations.md](integrations.md).

A `placeToTransition` link is deliberately not offered. PetriObjModelPaint
retired that link type, and writing the projection it used to would produce a
document the other side misreads.

## On the wire

A composed model exports as an **ISO/IEC 15909-2 conformant PNML dialect**
(version "2.1"), not a private format:

- One `<page>` per object, inside one `<net>`.
- Inter-object structure uses the standard's own reference-node mechanism,
  `<referencePlace>` and `<referenceTransition>`, rather than anything ad hoc.
- A `<petriObjectLinks>` block is still written for readers that do not
  implement reference nodes yet. It is a courtesy, never a second source of
  truth.

Every document the backend writes is checked against the real RELAX NG grammar
for the standard, not just hand-rolled invariant checks. That conformance is
what lets this project and PetriObjModelPaint's `petri-server` module read and
write each other's composed models.

If you are changing any of this, read the
[`pnml-standard` skill](../.claude/skills/pnml-standard/SKILL.md) first: it
lists the grammar files, the conformance suite, the golden fixtures, and the
rules that have already cost someone an afternoon.

## Simulating them

`POST /api/v1/simulate/composed` runs a composed model. The built-in Python
engine handles both flat nets and composed ones; a petri-server instance can
run them instead, see [configuration.md](configuration.md).
