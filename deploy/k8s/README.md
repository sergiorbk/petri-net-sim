# Kubernetes manifests

Plain YAML, no Helm, no Kustomize overlays. Read them, change the four things
that are yours, apply them.

```
namespace.yaml     the namespace everything else lives in
secret.yaml        a TEMPLATE. Do not apply as is, see below
configmap.yaml     non-secret configuration
api.yaml           Deployment + Service for petri-net-sim-api
web.yaml           Deployment + Service for petri-net-sim-web (nginx + the UI)
ingress.yaml       one host, TLS, and the timeouts streaming needs
petri-server.yaml  OPTIONAL, the Java simulation engine. See below
```

Postgres is **not** here on purpose. Run a managed database (RDS, Cloud SQL,
Neon) and point `DB_HOST` at it. A StatefulSet running your only copy of the
data is a decision to make deliberately, not to inherit from an example file.

## Before applying

**1. Generate the secrets.** The backend refuses to start in a deployed
environment without them, because a generated pair differs per pod: users get
logged out by whichever pod does not share the JWT secret, and stored BYOK
keys become unreadable without the master key that encrypted them.

```bash
kubectl create namespace petri-net-sim

kubectl -n petri-net-sim create secret generic petri-net-sim \
  --from-literal=AUTH_JWT_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=CREDENTIALS_MASTER_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  --from-literal=DB_PASSWORD='the database password' \
  --from-literal=DB_USER='petri_net_sim' \
  --from-literal=DB_NAME='petri_net_sim' \
  --from-literal=DB_HOST='your-postgres-host' \
  --from-literal=OAUTH_GOOGLE_CLIENT_ID='' \
  --from-literal=OAUTH_GOOGLE_CLIENT_SECRET=''
```

Keep those values. Losing `CREDENTIALS_MASTER_KEY` means every user re-enters
their LLM key; losing `AUTH_JWT_SECRET_KEY` only logs everyone out.

**2. Edit `configmap.yaml`** for your public URL, and `ingress.yaml` for your
host, TLS secret and ingress class.

**3. Build the images.** This project publishes one image, the all-in-one,
and that is a single container which cannot be split across two Deployments.
The two halves are yours to build and push:

```bash
REG=your-registry
docker build -t $REG/petri-net-sim-api:v1.0.0 ./backend
docker build -t $REG/petri-net-sim-web:v1.0.0 --target prod ./frontend
docker push $REG/petri-net-sim-api:v1.0.0
docker push $REG/petri-net-sim-web:v1.0.0
```

Name them in `api.yaml` and `web.yaml`, pinned to a tag rather than `latest`:
nothing tells a Deployment that a mutable tag moved, and a pinned tag is what
makes a rollback `kubectl rollout undo`.

```bash
kubectl -n petri-net-sim set image deployment/petri-net-sim-api   api=$REG/petri-net-sim-api:v1.1.0
```

## Apply

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/api.yaml
kubectl apply -f deploy/k8s/web.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

`secret.yaml` is a template showing the keys the Deployment expects. Create the
real Secret with the command above, or with your secret manager, and keep the
values out of git.

## What scales and what does not

**The web pods** are static assets behind nginx. Scale them freely.

**The API pods** are stateless for everything the browser does: chats,
messages, nets and generated files live in Postgres, and a net is rebuilt from
it per request. Scale them, with two caveats:

- **Rate limiting counts in process memory** (see
  `backend/src/api/shared/rate_limit.py`), so with N replicas the effective
  ceiling is up to N times the configured one.
- **MCP sessions live in process memory** (`backend/src/mcp/session_store.py`).
  An MCP client whose requests land on different pods loses its session. Until
  that store is shared, either keep the API at one replica if MCP matters, or
  route `/mcp` to a single pod, or turn MCP off in the ConfigMap
  (`MCP_ENABLED: "false"`) on the replicas that serve the browser.

The API Deployment therefore starts at **1 replica** and says why in a comment,
rather than shipping an example that quietly breaks a feature.

## Probes

The backend exposes all three kinds, so the manifests use each for what it is
for:

| Probe | Path | Meaning |
|-------|------|---------|
| startup | `/health/startup` | Migrations and boot are done. Buys a slow first start without a long liveness delay |
| readiness | `/health/ready` | Dependencies answer. A pod that cannot reach the database leaves the Service |
| liveness | `/health/live` | The process is alive. Failing it restarts the container |

Readiness checks the database, so a database blip takes pods out of rotation
rather than restarting them. That is the intended split: liveness is about the
process, readiness is about its dependencies.

## The Java simulation engine, optionally

[petri-server](https://github.com/StetsenkoInna/PetriObjModelPaint/tree/master/petri-server)
is PetriObjModelPaint's Spring Boot service, and it can run simulations
instead of the Python engine in the API pods. `petri-server.yaml` deploys it,
and `configmap.yaml` then needs two lines:

```yaml
SIMULATION_ENGINE: "remote"
SIMULATION_REMOTE_URL: "http://petri-server:8080"
```

Two things to know before you do it:

- **You build the image.** It is another project's artifact, so our release
  pipeline does not build it and our registry does not host it. The manifest
  says how, and the build context is that repository's root because it is a
  Maven reactor build.
- **It has no authentication.** Anything that can reach it can run a
  simulation on it. Keep it ClusterIP, keep it out of the Ingress, and keep
  the NetworkPolicy in that file, which lets only the API pods in.

`SIMULATION_REMOTE_FALLBACK` (default `true`) decides what happens when it is
unreachable: run the model on the built-in engine and say so on the stream, or
report the failure and simulate nothing.

The engine choice is per deployment, not per user, and the API pods stay
identical either way: they call `/api/v1/simulation/stream` for a flat net and
`/api/v2/simulation/stream` for a composed model, both Server-Sent Events.
