FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# API base baked into the SPA at build time. Default matches the dev fallback in
# src/api/client.ts (frontend talks to the backend on localhost:8000). A reverse
# -proxy deployment that serves panel + API on one origin builds with an empty
# value (VITE_API_URL=) so the SPA uses relative /api paths and needs no CORS.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
