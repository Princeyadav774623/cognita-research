# Build Stage
# Node 22 LTS — vite 8 requires ^20.19.0 || >=22.12.0.
FROM node:22-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

# Vite inlines VITE_* vars into the bundle at build time, so they have to be
# present during `npm run build` — passing them to the runtime container has
# no effect. VITE_API_URL is intentionally allowed to be empty: that makes the
# bundle use same-origin paths and go through nginx (see nginx.conf.template).
ARG VITE_API_URL=""
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY

COPY . .
RUN npm run build

# Production Stage (Nginx)
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
# Where /api and /ws are proxied to. The compose service by default; set it to
# the API's URL anywhere else (e.g. a Cloud Run service URL).
ENV BACKEND_URL=http://backend:8000

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
