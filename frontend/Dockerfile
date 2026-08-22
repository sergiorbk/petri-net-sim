# ---- Build stage: compile the production bundle ----------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Dev stage: Vite dev server with hot reload ----------------------------
# Used by docker-compose.dev.yml (build target: dev). Source is bind-mounted
# at runtime, so this stage only needs the toolchain and dependencies.
FROM node:22-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 6203
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "6203"]

# ---- Production stage: static assets served by nginx -----------------------
# Last stage => default target for a plain `docker build`.
FROM nginx:alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
