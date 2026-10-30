# PetriObjModelPaint

[PetriObjModelPaint](https://github.com/StetsenkoInna/PetriObjModelPaint) is a
cross-platform desktop editor and simulator for both classical Petri nets and
Petri-object models, created at Igor Sikorsky Kyiv Polytechnic Institute by
professor **Inna Stetsenko**
([@StetsenkoInna](https://github.com/StetsenkoInna)), who founded the
Petri-object approach and supervised the thesis this project came out of.

Petri Net Sim is that idea taken to the browser and handed to an agent. The
two are friendly projects, and they meet in two concrete places.

## They open each other's files

Save a model here, open it there, or the other way round.

- **Flat nets** travel as ordinary PNML, which TINA and CPN Tools read as
  well.
- **Composed Petri-object models** travel in the ISO/IEC 15909-2 conformant
  dialect `petri-server` reads and writes, checked against that project's own
  parser rather than inferred from its documentation.

Whichever built the model, an editor, a chat agent or an API call, the other
tool opens it. [petri-objects.md](petri-objects.md) covers what is inside such
a document, and the
[`pnml-standard` skill](../.claude/skills/pnml-standard/SKILL.md) covers the
grammar it is held to.

## Its engine can run your models

PetriObjModelPaint's `petri-server` module is a Java simulation engine. This
app can compute on it instead of its own Python engine.

Point at a running instance:

```env
SIMULATION_ENGINE=remote
SIMULATION_REMOTE_URL=http://petri-server:8080
```

Or bring one up alongside this stack, from a PetriObjModelPaint checkout:

```bash
# .env, if the checkout is not a sibling of this repo
# PETRI_SERVER_BUILD_CONTEXT=../PetriObjModelPaint

docker compose --profile petri-server up -d --build
```

It listens on `PETRI_SERVER_PORT`, 6205 by default, and the Compose profile
binds it to `127.0.0.1` rather than every interface. That is not caution for
its own sake, see the warning below.

> [!NOTE]
> Setting a URL is not on its own a request to compute there. The engine has
> to be switched explicitly, so a leftover address cannot quietly route every
> run through a service nobody deployed.

`SIMULATION_REMOTE_FALLBACK` decides what happens when the remote engine is
unreachable: `true` runs the model on the built-in engine and says so on the
stream, `false` reports the failure and simulates nothing.

### What it is, exactly

A Spring Boot service on port 8080, with two API versions matching the two
kinds of model:

| | Endpoint | For |
|---|---|---|
| **v1** | `POST /api/v1/simulation/stream` | one flat net |
| **v2** | `POST /api/v2/simulation/stream` | a composed Petri-object model, with statistics per object |
| | `POST /api/v2/model/parse` | round-trips PNML through its own parser |

Both stream Server-Sent Events, and both are what this backend calls when
`SIMULATION_ENGINE=remote`. There is also a STOMP WebSocket endpoint at `/ws`
and pause, resume, stop and status endpoints per simulation, which this app
does not use.

It documents itself: **Swagger UI at `/docs`**, the schema at
`/openapi.json`, health at `/actuator/health`. It does **not** speak MCP, so
an agent reaches it only through this app.

> [!WARNING]
> petri-server has no authentication of its own. Anything that can reach it
> can run a simulation on it. Keep it on a private network: bound to
> localhost on a VM, ClusterIP with a NetworkPolicy in Kubernetes, never
> behind a public Ingress.

### Deploying it as a separate service

On a VM, the Compose profile above is the whole story: one more container on
the same network, reached by service name.

In Kubernetes, [`deploy/k8s/petri-server.yaml`](../deploy/k8s/petri-server.yaml)
has a Deployment, a ClusterIP Service and a NetworkPolicy that lets only the
API pods in. You build the image yourself from a PetriObjModelPaint checkout,
because our release pipeline builds this project's artifacts and not another
project's:

```bash
git clone https://github.com/StetsenkoInna/PetriObjModelPaint
cd PetriObjModelPaint
docker build -f petri-server/Dockerfile -t your-registry/petri-server:2.5.0 .
```

The build context is that repository's root, not `petri-server/`: it is a
Maven reactor build and needs every module's `pom.xml` on disk.
