FROM node:22-alpine AS dependencies

WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS builder

WORKDIR /app
COPY . .
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
# Prisma generation is part of the existing Next.js build; it does not connect
# to this placeholder during image construction.
ENV DATABASE_URL=postgresql://placeholder:placeholder@127.0.0.1:5432/commercelens
RUN pnpm build && pnpm prune --prod

FROM node:22-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/src/generated ./src/generated

EXPOSE 3000
CMD ["./node_modules/.bin/next", "start", "-H", "0.0.0.0", "-p", "3000"]
