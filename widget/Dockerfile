# Owner: Charbel

# ── build stage (placeholder) ────────────────────────────────
# Charbel: replace with: COPY package*.json ./ && npm ci && COPY src/ ./src/ && npm run build
FROM node:20-alpine AS build
WORKDIR /app
RUN mkdir -p dist && \
    printf '<!DOCTYPE html>\n<html><head><meta charset="UTF-8"><title>Concierge Widget</title></head>\n<body><p>Widget — placeholder. Charbel to implement.</p></body></html>\n' \
    > dist/index.html

# ── serve stage ──────────────────────────────────────────────
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
