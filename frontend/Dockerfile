FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# VITE_* vars must be supplied at build time (Vite inlines them into the
# static bundle - they are not secrets, only public config like the
# Keycloak realm URL).
RUN npm run build

FROM nginx:1.27-alpine
# Non-root nginx image; strip default content
RUN rm -rf /usr/share/nginx/html/*
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
