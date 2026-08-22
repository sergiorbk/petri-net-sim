# Deploying to a server

Publishing a release pushes one image to GHCR, and a deploy is then just a
`pull` on the server. No source checkout to build, no toolchain, no build
memory on a small VM.

```
ghcr.io/sergiorbk/petri-net-sim-local:v1.0.0
```

The all-in-one: the UI, the API and PostgreSQL in one container,
`linux/amd64`. The name says `-local` because the image defaults to
`AUTH_MODE=single_user`, no login at all: it is built for one person running
it for themselves, and needs `AUTH_MODE=multi` before it faces a network.

**Nothing else is published**, and that is a decision rather than an
oversight: an image in a public registry reads as a promise to keep it
working, and the artifact this project stands behind is the one somebody runs
for themselves. The three-container stack and the Kubernetes manifests are
supported, but their two images are yours to build:

```bash
REG=your-registry
docker build -t $REG/petri-net-sim-api:v1.0.0 ./backend
docker build -t $REG/petri-net-sim-web:v1.0.0 --target prod ./frontend
docker push $REG/petri-net-sim-api:v1.0.0
docker push $REG/petri-net-sim-web:v1.0.0
```

Then set `IMAGE_REGISTRY=$REG` in the server's `.env`, which
`docker-compose.prod.yml` reads. It has no default on purpose: an unset
variable fails by name before anything runs, while a default pointing at a
registry with no such image fails later, as a confusing 404.

If you deploy to ARM (Graviton, Oracle Ampere, a Pi), add `platforms:
linux/amd64,linux/arm64` to the build step in
[`release.yml`](../.github/workflows/release.yml) first, and expect a much
slower release build.

## One container or three

The all-in-one is a real deployment option, not just a demo. On a single VM
serving a team it is the smaller thing to operate: one image to pull, one
container to restart, one volume holding both the database and the generated
secrets.

Take the three-container split when you want one of these:

| You want | Why the split |
|----------|---------------|
| **Postgres somewhere else** | A managed database (RDS, Cloud SQL, Neon) or a container you back up and upgrade on its own schedule. The all-in-one's Postgres lives inside the app image, so an app update recreates the process serving your data |
| **To restart the API alone** | In one container, bouncing the backend bounces Postgres with it |
| **More than one API replica** | Or Kubernetes, or any scheduler that expects one process per container |
| **nginx in front of the assets** | The all-in-one serves the built UI from uvicorn itself. Fine at this scale, but it is not nginx |

Nothing is lost by starting with one container: the database is in a named
volume, so moving to the split later is a `pg_dump` and a restore.

> [!WARNING]
> The all-in-one defaults to `AUTH_MODE=single_user`, which means **no login
> at all**: everyone who reaches the port is the same account. Before putting
> it on a public address, set `AUTH_MODE=multi` and `APP_ENV=prod` in `.env`.

## Which host

Any Linux box with Docker. Two things matter: **RAM** and a **persistent
disk**.

| Option | Cost | Notes |
|--------|------|-------|
| **Oracle Cloud Always Free** | free, indefinitely | The most generous free tier: an Ampere ARM VM up to 4 vCPU / 24 GB. ARM, so build multi-arch images first. The AMD micro shapes are x86 but only 1 GB |
| **AWS EC2 free tier** | free for 12 months | `t3.micro` is 1 GB, which is tight for API + Postgres + nginx. `t3.small` (2 GB) is the comfortable floor |
| **Hetzner, Netcup, and similar** | a few euros a month | 2 to 4 GB for the price of a coffee, no expiry, no card games |
| **Fly.io, Render, Railway** | free tiers with catches | Built for stateless apps. Postgres is a separate paid add-on and free instances sleep, which a simulation server should not |

Recommendation: **2 GB of RAM minimum**. Below that Postgres and the agent
fight over memory. If the free tier matters more than anything else, Oracle
Always Free is the only one that is genuinely free forever and large enough.

## Prepare the server, once

```bash
# 1. Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out and back in

# 2. The compose files, from this repo
git clone https://github.com/sergiorbk/petri-net-sim.git ~/petri-net-sim
cd ~/petri-net-sim

# 3. This deployment's configuration. Never committed.
cp .env.example .env
```

Edit `.env`:

```env
APP_ENV=prod
APP_PUBLIC_URL=https://your.domain
DB_PASSWORD=<something long and random>
AUTH_JWT_SECRET_KEY=<openssl rand -hex 32>
CREDENTIALS_MASTER_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

> [!IMPORTANT]
> With `APP_ENV=prod` these two are not optional, and nothing will invent them
> for you: the entrypoint refuses to start rather than auto-generate secrets in
> a deployed environment. A generated pair differs per container, so a second
> replica or a replaced volume logs every user out and makes stored BYOK keys
> unreadable. Auto-generation stays exactly where it belongs, on a laptop.

For the all-in-one, add the line that turns login on:

```env
AUTH_MODE=multi
```

Then start it. One container:

```bash
docker compose -f docker-compose.allinone.yml pull
docker compose -f docker-compose.allinone.yml up -d
```

Everything on port 6204. Or three:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

UI on 6200, API on 6201.

Either way, put a TLS-terminating reverse proxy in front rather than exposing
those ports directly. There is an example config in
[`deploy/nginx/app.conf.example`](../deploy/nginx/app.conf.example), and Caddy
will do the same job in three lines with automatic certificates.

## Automatic delivery

[`deploy.yml`](../.github/workflows/deploy.yml) runs those two commands over
SSH after every published release, and on demand from the Actions tab when you
want to redeploy or pin a specific tag. It deploys the all-in-one by default,
and the three-container stack when `DEPLOY_MODE` says `stack`, which then
needs `IMAGE_REGISTRY` set on the server and your own images pushed to it.

Give it a key of its own rather than reusing yours:

```bash
# on your machine
ssh-keygen -t ed25519 -f ~/.ssh/petri_deploy -C "github-actions-deploy" -N ""
ssh-copy-id -i ~/.ssh/petri_deploy.pub ubuntu@your.server
cat ~/.ssh/petri_deploy          # the private key, for the secret below
```

Then in **Settings, Secrets and variables, Actions**, under Secrets:

| Secret | Value |
|--------|-------|
| `DEPLOY_HOST` | Server hostname or IP |
| `DEPLOY_USER` | SSH user, `ubuntu` on a stock EC2 Ubuntu AMI |
| `DEPLOY_SSH_KEY` | The whole private key file, BEGIN and END lines included |
| `DEPLOY_PORT` | Optional, defaults to 22 |
| `DEPLOY_PATH` | Optional, defaults to `~/petri-net-sim` |

And under Variables, if the defaults do not fit:

| Variable | Default | What |
|----------|---------|------|
| `DEPLOY_MODE` | `allinone` | `allinone` deploys the single container, `stack` deploys the three |
| `DEPLOY_HEALTH_PORT` | 6204 or 6201 | The port the workflow probes afterwards, when either is remapped |

Without `DEPLOY_HOST` the job skips rather than fails, so the workflow can sit
in the repo unused.

> [!TIP]
> Keep the deploy key unprivileged: it needs to run `docker compose` in one
> directory, nothing more. If the server's SSH is reachable from the internet,
> restrict the key with `command=` in `authorized_keys` or put the box behind
> a VPN, since a repository secret is only as safe as the account holding it.

## Updating

Publishing a release is enough: `bump-version.yml` tags it, `release.yml`
builds the images, `deploy.yml` ships them. To move a running server to a
different tag without a release, run **Deploy** from the Actions tab and give
it the tag.

Rolling back is the same button with the previous tag.

## Kubernetes

The two split images are one process each, which is what a scheduler expects,
and you build them yourself as above:
a Deployment for `petri-net-sim-api`, a Deployment for `petri-net-sim-web`,
and Postgres as a StatefulSet or, better, a managed database outside the
cluster. The environment variables are the same ones
[configuration.md](configuration.md) lists, and `/health/live`, `/health/ready`
and `/health/startup` are there for the three probe kinds.

The all-in-one image cannot be split that way: it runs Postgres and uvicorn in
one process tree, under tini, on one port. It is a single-VM artifact by
design.

Manifests live in [`deploy/k8s/`](../deploy/k8s/): namespace, ConfigMap, a
Secret template, a Deployment and Service for each half, and an Ingress with
the timeouts streaming needs. Plain YAML, no Helm.
[`deploy/k8s/README.md`](../deploy/k8s/README.md) covers what to change before
applying and, more importantly, what scales and what does not.

## With the Java simulation engine

Any of the shapes above can compute simulations on
[petri-server](petriobjmodelpaint.md) instead of the Python engine, as one
more service:

| Shape | How |
|-------|-----|
| VM, Compose | `docker compose --profile petri-server up -d --build`, then `SIMULATION_ENGINE=remote` and `SIMULATION_REMOTE_URL=http://petri-server:8080` |
| Kubernetes | [`deploy/k8s/petri-server.yaml`](../deploy/k8s/petri-server.yaml), then the same two settings in the ConfigMap |
| All-in-one | Not this one. It is a single container by definition; run the stack instead |

Its image is not in our registry and the release pipeline does not build it:
it belongs to another project, and building someone else's code into our
artifacts would make our releases depend on their build. Build it from a
PetriObjModelPaint checkout and push it to your own registry.

> [!WARNING]
> petri-server has no authentication. Keep it on a private network, never
> behind a public Ingress.
