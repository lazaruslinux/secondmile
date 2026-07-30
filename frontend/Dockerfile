# Two stages: the first needs the whole Node toolchain to compile the app, the
# second ships only the finished static files on a small nginx image, so the
# toolchain never reaches production.
# Both stages are digest-pinned for reproducible builds and against tag
# poisoning; the readable tags ride along in comments and Dependabot bumps the
# digests.

# node:26-alpine
FROM node:26-alpine@sha256:e88a35be04478413b7c71c455cd9865de9b9360e1f43456be5951032d7ac1a66 AS build

WORKDIR /app

# Lockfiles first, so Docker reuses the install layer until the dependencies
# themselves change rather than on every source edit.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# nginx:1.31-alpine
FROM nginx:1.31-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
