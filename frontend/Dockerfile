FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json tsconfig.json vite.config.ts index.html ./
COPY src ./src
# Pinning electron-to-chromium through package.json overrides avoids transient
# npm registry resolutions to an unavailable/yanked tarball.
RUN npm config set registry https://registry.npmjs.org/ \
    && npm ci --no-audit --no-fund \
    && npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
