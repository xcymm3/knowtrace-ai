import { config } from "dotenv";
import { defineConfig } from "prisma/config";

config({ path: ".env" });
config({ path: ".env.local", override: true });

// `prisma generate` only produces the client; it does not open a database
// connection. A Vercel preview of the demo workspace should therefore build
// before a Supabase project has been configured. Runtime database access still
// requires the real DATABASE_URL in src/lib/prisma.ts.
const databaseUrl =
  process.env.DATABASE_URL?.trim() || "postgresql://build:build@localhost:5432/commercelens";

export default defineConfig({
  schema: "prisma/schema.prisma",
  migrations: {
    path: "prisma/migrations",
  },
  datasource: {
    url: databaseUrl,
  },
});
