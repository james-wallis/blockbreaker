// Vercel serverless function backing the shared Block Breaker leaderboard.
//
// GET  /api/scores            -> { scores: [{ name, score }, ...] }  (top 10, desc)
// POST /api/scores {name,score} -> validates, inserts, returns the new top 10
//
// Turso credentials are read from env vars (TURSO_DATABASE_URL, TURSO_AUTH_TOKEN)
// and never reach the browser. The game is client-side, so scores are inherently
// spoofable; the validation below is light sanity-checking, not anti-cheat.
import { createClient } from "@libsql/client";

const db = createClient({
  url: process.env.TURSO_DATABASE_URL,
  authToken: process.env.TURSO_AUTH_TOKEN,
});

const MAX_SCORE = 1_000_000; // generous sanity cap
const TOP_N = 10;

const TOP_QUERY =
  "SELECT name, score FROM scores ORDER BY score DESC, created_at ASC LIMIT " +
  TOP_N;

export default async function handler(req, res) {
  // Allow the game to call this even when embedded from another origin.
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(204).end();

  try {
    if (req.method === "GET") {
      const rs = await db.execute(TOP_QUERY);
      return res.status(200).json({ scores: rs.rows });
    }

    if (req.method === "POST") {
      const body =
        typeof req.body === "string" ? JSON.parse(req.body || "{}") : req.body || {};
      let name = String(body.name ?? "").trim().slice(0, 10);
      const score = Number(body.score);

      if (name.length < 3 || name.length > 10) {
        return res.status(400).json({ error: "name must be 3-10 characters" });
      }
      if (!Number.isInteger(score) || score < 0 || score > MAX_SCORE) {
        return res.status(400).json({ error: "invalid score" });
      }

      await db.execute({
        sql: "INSERT INTO scores (name, score, created_at) VALUES (?, ?, ?)",
        args: [name, score, Date.now()],
      });

      const rs = await db.execute(TOP_QUERY);
      return res.status(200).json({ scores: rs.rows });
    }

    return res.status(405).json({ error: "method not allowed" });
  } catch (err) {
    console.error("scores api error:", err);
    return res.status(500).json({ error: "server error" });
  }
}
