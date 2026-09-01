# Two stages: the first needs the whole Node toolchain to compile the app, the
# second ships only the finished static files on a small nginx image, so the
# toolchain never reaches production.
# Both stages are digest-pinned for reproducible builds and against tag
# poisoning; the readable tags ride along in comments and Dependabot bumps the
# digests.

# node:26-alpine
FROM node:26-alpine@sha256:2d984a15c9b54fd0aeb608b8e0d0d83529eb34d2966db27a1fb4f1edc3d298a3 AS build

WORKDIR /app

# Lockfiles first, so Docker reuses the install layer until the dependencies
# themselves change rather than on every source edit.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# nginx:1.31-alpine
FROM nginx:1.31-alpine@sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
