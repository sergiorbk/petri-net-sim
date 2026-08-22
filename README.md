<div align="center">

# Petri Net Sim

**An editor, a simulator, and a natural-language generator for Petri nets and
Petri-object models, in one place.**

Draw a model, describe it in plain language and let an agent build it, then
run stochastic simulations, read the charts and export the numbers to a
spreadsheet. For researchers who study systems by simulating them, for
students learning Petri nets and system modelling, and for anyone who would
rather think about the model than about the tooling.

[![License](https://img.shields.io/badge/license-PolyForm_Noncommercial_1.0.0-1f6feb?style=flat-square)](LICENSE)
[![PNML](https://img.shields.io/badge/PNML-ISO%2FIEC_15909--2-2ea043?style=flat-square)](docs/petri-objects.md)
[![MCP](https://img.shields.io/badge/MCP-server_built_in-8250df?style=flat-square)](docs/integrations.md)
[![API](https://img.shields.io/badge/API-OpenAI--compatible-412991?style=flat-square)](docs/integrations.md)

![React 18](https://img.shields.io/badge/React_18-20232A?style=flat-square&logo=react&logoColor=61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white)
![Python 3.13](https://img.shields.io/badge/Python_3.13-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat-square&logo=langchain&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)

<img src="docs/assets/chat.webp" alt="A call centre described in one sentence; the agent answers and the Petri net appears on the canvas" width="900">

</div>

## Try it

Nothing to clone, the image comes down on its own:

```bash
docker run -d --name petri-net-sim -p 6204:8000 \
  -e APP_PUBLIC_URL=http://localhost:6204 \
  -v petri-net-sim-data:/data \
  ghcr.io/sergiorbk/petri-net-sim-local:latest
```

Or, from a checkout of this repository:

```bash
docker compose -f docker-compose.allinone.yml pull
docker compose -f docker-compose.allinone.yml up -d
```

Either way, open **http://localhost:6204**. One container with the UI, the API
and PostgreSQL inside, no signup, nothing to configure. Add your own LLM key
in Settings and start describing a system.

> [!IMPORTANT]
> The image is named `-local` because it defaults to `AUTH_MODE=single_user`:
> no login at all, everyone who reaches the port is the same account. Right
> for one person running it for themselves, wrong for anything reachable by
> others. See [docs/deployment.md](docs/deployment.md) before it faces a
> network.

> [!NOTE]
> The app is **BYOK (Bring Your Own Key)**: each user brings their own key
> (OpenAI / Anthropic / Ollama). There is no shared server-side key, and
> nothing reaches a provider until someone supplies one.

Want accounts, hot reload, or a real deployment instead? Three more ways to
run it are in [docs/running.md](docs/running.md).

## Three tools, one model

| | |
|---|---|
| **Editor** | A canvas with places, transitions, arcs, weights, priorities and timing. Draw a net, or fix the one the agent built |
| **Simulator** | Stochastic runs in the browser or on a remote engine. Watch it play, step through it, or jump straight to the final state |
| **Generator** | Describe a production line or a queueing system in plain language; an agent composes it from a catalog of reusable patterns and streams the net as it goes |

All three work on the same model, flat or composed, and nothing is a
one-way door.

**The editor.** Places, transitions and arcs, with each transition's
distribution and delay under its name.

![The canvas: a queue feeding two machines, each transition labelled with its distribution and delay](docs/assets/editor.png)

**The simulator.** Tokens move as the run plays; the same run can be stepped
one firing at a time, or skipped straight to its final state.

![A simulation running: tokens moving through the net, the firing transition highlighted](docs/assets/simulation.gif)

**The statistics.** Every place and transition plotted against the simulation
clock, with a summary table per series. The run [exports](docs/simulation.md)
as CSV for Excel or PowerBI, and the charts as PNG or SVG for a paper.

![The statistics panel: tokens per place and transition buffers over time, with CSV, PNG and SVG export](docs/assets/statistics.png)

And whichever tool built it, the model is not stuck here:

| | |
|---|---|
| **Compose it** | Several named [Petri-objects](docs/petri-objects.md) linked together, so a large model stays a set of small readable ones |
| **Take it elsewhere** | ISO/IEC 15909-2 conformant PNML, readable by PetriObjModelPaint, TINA and CPN Tools |
| **Drive it from code** | An [MCP server and an OpenAI-compatible API](docs/integrations.md), on keys you issue yourself |

![A composed model: Generator, Machine and Counter as three framed nets, joined by dashed place-fusion links](docs/assets/petri-objects.png)

Each frame above is its own net with its own places and transitions. The
dashed links are shared places: one object's Out **is** the next object's In,
so tokens are not copied between them. [More on Petri-objects](docs/petri-objects.md).

## Documentation

| Guide | What it covers |
|-------|----------------|
| [Running](docs/running.md) | The four ways to run it, ports, make targets |
| [Simulation](docs/simulation.md) | Starting a run, snapshot modes, the statistics panel, exporting results |
| [Configuration](docs/configuration.md) | Environment variables, secrets, choosing a simulation engine |
| [Deployment](docs/deployment.md) | Publishing images, picking a host, automatic delivery over SSH |
| [Connecting other tools](docs/integrations.md) | MCP and the HTTP API: keys, URLs, the per-account switches |
| [Petri-objects](docs/petri-objects.md) | Composing a model from linked nets, and what that looks like on the wire |
| [PetriObjModelPaint](docs/petriobjmodelpaint.md) | The desktop project this one comes from, and exchanging files with it |
| [`backend/`](backend/README.md) and [`frontend/`](frontend/README.md) | Running and developing either half on its own |
| [`AGENTS.md`](AGENTS.md) | Layout, commands and house rules, for coding agents and new contributors |

## Contributing

One trunk, and everything reaches it through a pull request: branch, open a
PR, let CI gate it, merge, delete the branch. Releases are semver tags cut
from that trunk, and publishing a GitHub Release from a tag is what builds
and ships the images. [`AGENTS.md`](AGENTS.md) has the details, along with
the layout and the house rules.

## Where this comes from

This is the result of my 2026 bachelor's thesis at **Igor Sikorsky Kyiv
Polytechnic Institute**, Faculty of Informatics and Computer Engineering,
program Information Systems Software Engineering.

Supervisor: **Inna Stetsenko** ([@StetsenkoInna](https://github.com/StetsenkoInna))

Author: Serhii Rybak ([@sergiorbk](https://github.com/sergiorbk))

## License

Source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE).
Free to use, study, modify and share for **any noncommercial purpose**.
**Commercial use requires a separate license** from the author: Serhii Rybak
([@sergiorbk](https://github.com/sergiorbk)), <sergey24rybak@gmail.com>.

Copyright © 2026 Serhii Rybak ([@sergiorbk](https://github.com/sergiorbk)). All rights reserved.

<sub>The RELAX NG grammars under
[`backend/tests/schema/`](backend/tests/schema), used to validate exported
PNML against the real ISO/IEC 15909-2 standard, are vendored from the pnml.org
reference schema and carry their own copyright (Michael Weber, Ekkart Kindler,
Christian Stehno, Lom Hillah, 2001-2009). They are test fixtures, not shipped
code, and are not covered by the license above.</sub>
