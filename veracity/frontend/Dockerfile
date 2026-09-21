# syntax=docker/dockerfile:1

FROM node:22-alpine AS build
WORKDIR /app
# package files first: this layer only rebuilds when dependencies change, not
# on every source edit.
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build


FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# nginx's own user, and a pid path it can write to as non-root.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://localhost:8080/ >/dev/null || exit 1
