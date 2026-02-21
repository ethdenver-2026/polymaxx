FROM node:20-alpine

WORKDIR /app/dashboard

COPY dashboard/package*.json ./
RUN npm ci --no-audit --no-fund

COPY dashboard/ ./

EXPOSE 5173
EXPOSE 5174

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"]
