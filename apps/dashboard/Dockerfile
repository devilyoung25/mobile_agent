# Dashboard (TanStack Start + Vite). Build then preview. The API base URL is a
# build-time arg (Vite inlines VITE_* at build).
FROM node:22-slim

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

ARG VITE_DASHBOARD_API_BASE_URL=http://localhost:2024
ENV VITE_DASHBOARD_API_BASE_URL=$VITE_DASHBOARD_API_BASE_URL
RUN npm run build

EXPOSE 3000
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "3000"]
