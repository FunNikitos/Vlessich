# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS build
ARG VITE_API_BASE_URL=/api
ARG VITE_TURNSTILE_SITEKEY=
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_TURNSTILE_SITEKEY=${VITE_TURNSTILE_SITEKEY}
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
