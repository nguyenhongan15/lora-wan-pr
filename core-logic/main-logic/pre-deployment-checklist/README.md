# Pre-Deployment Checklist

Shipping to production is the moment a small oversight becomes a public incident. This checklist walks through the items I verify before pressing deploy — what each one means, and why skipping it usually ends badly.

## 1. Authorization — Users Locked to Their Own Data

**What it means.** Authentication proves *who* you are. Authorization decides *what you're allowed to touch*. Every protected endpoint must check that the requesting user actually owns the resource they're asking for — usually by matching the resource's owner ID against the authenticated user's UUID.

**Why it matters before deploy.** This is the most common and most damaging class of bug in web apps: **IDOR** (Insecure Direct Object Reference). If `/api/orders/123` returns the order without checking that order `123` belongs to the caller, anyone can iterate IDs and read other users' data. Using UUIDs instead of sequential IDs makes guessing harder, but it is **not** authorization — you still need an explicit ownership check on every request.

## 2. Password Reset Links Expire

**What it means.** A password reset link contains a single-use token. That token must have a short lifetime (commonly 15–60 minutes) and must be invalidated as soon as it's used or as soon as a new reset is requested.

**Why it matters before deploy.** Reset links land in email inboxes, which can be forwarded, screenshotted, cached on shared devices, or leaked through breaches. A non-expiring token is a permanent backdoor into the account. A short TTL shrinks the window of attack to minutes instead of forever.

## 3. Input Validation — SQL Injection and XSS

**What it means.** Treat every value coming from the client as hostile. Validate types, lengths, and formats. Use **parameterized queries / ORMs** so user input cannot change the shape of a SQL statement. Escape or sanitize anything rendered back into HTML so injected `<script>` tags don't execute in someone else's browser.

**Why it matters before deploy.** SQL injection can dump or drop your entire database. XSS can hijack sessions, steal tokens, and pivot into account takeover. Both have lived in the OWASP Top 10 for over a decade because they keep working — usually on a single forgotten field.

## 4. CORS — Lock the API to Your Own Domain

**What it means.** **CORS** (Cross-Origin Resource Sharing) tells browsers which origins are allowed to call your API. In production, the allowed origin list should be your own domains — not `*`, not `localhost`, not whatever was convenient during development.

**Why it matters before deploy.** A wide-open CORS policy lets malicious sites make authenticated requests to your API from a victim's browser, which can leak data or trigger actions on behalf of the user. Many teams ship `Access-Control-Allow-Origin: *` from a dev config and only notice when something abuses it.

> CORS is a **browser** protection. It does not stop server-to-server attacks. Authentication and authorization still do the real work.

## 5. Rate Limiting

**What it means.** Cap how many requests a single client (by IP, user, or API key) can make in a given window. Apply tighter limits on expensive or abusable endpoints — login, password reset, signup, search, anything that hits the database hard or sends email/SMS.

**Why it matters before deploy.** Without rate limiting you're exposed to:
- **Brute-force attacks** on login and reset endpoints
- **Credential stuffing** at massive scale
- **Denial of service** from a single noisy client
- **A surprise cloud bill** when someone loops your most expensive endpoint overnight

A rate limiter is one of the cheapest controls you can add and one of the most expensive ones to forget.

## 6. Error Handling — Custom Error Screens

**What it means.** Every failure state — 400, 401, 403, 404, 429, 500 — should return a clean, user-friendly page or a structured JSON error. Internal exceptions, stack traces, framework debug pages, and database errors must never reach the client in production.

**Why it matters before deploy.** Default debug pages (Django's yellow page, Flask's debugger, Node's stack trace) leak file paths, library versions, environment variables, query fragments, and sometimes secrets. Attackers use that information to fingerprint your stack and craft targeted exploits. Beyond security, custom error screens are the difference between a user retrying and a user leaving.

## 7. Database Performance — Indexes on Hot Queries

**What it means.** An index is a precomputed lookup structure that lets the database find rows without scanning the whole table. Add indexes on the columns you actually filter, join, or sort by — typically foreign keys and the fields used in your hottest `WHERE` clauses.

**Why it matters before deploy.** A query that runs in 5ms on 1,000 dev rows can take 30 seconds on 10 million production rows without an index. That single slow query can lock connections, exhaust the connection pool, and take the whole app down under real traffic.

**Why not index everything.** Every index makes writes slower (the index has to be updated on every insert/update/delete) and uses disk and memory. The right answer is *targeted* indexing: cover the queries that run constantly, leave the rest alone, and revisit with `EXPLAIN` when something gets slow.

## 8. Logging and Monitoring

**What it means.** Two distinct things:
- **Logging** — a record of what happened: requests, errors, key business events. Structured (JSON) logs are easier to search than free-form strings.
- **Monitoring & alerting** — automated checks on top of logs and metrics that page you when something is actually broken: error rate spikes, latency jumps, 5xx surges, jobs failing, uptime checks failing.

**Why it matters before deploy.** If you ship without logs, you are debugging production incidents blind — you'll have a screenshot from a user and nothing else. If you ship without alerts, you'll find out about outages from customers on social media instead of from your phone. The goal is simple: **know about problems before your users do**, and have enough context to fix them quickly.

## 9. Rollback Strategy — Blue-Green Deployment

**What it means.** **Blue-green deployment** runs two identical production environments. One ("blue") serves all live traffic. You deploy the new version to the idle environment ("green"), verify it, then flip the load balancer to send traffic to green. Blue stays warm and untouched — if green misbehaves, you flip the load balancer back. No rebuild, no waiting, no panic.

**Why it matters before deploy.** Every deployment can fail in ways your tests didn't catch — config drift, an unmigrated table, a dependency that behaves differently in prod. Without a rollback plan, your incident response is "fix forward under pressure," which is how 5-minute outages become 5-hour ones. A blue-green setup (or any equivalent like canary or rolling deploys with a tested rollback path) turns a bad deploy into a load-balancer flip.

## TL;DR

Before you deploy, walk the checklist:

1. **Authorization** — every endpoint enforces ownership, not just authentication
2. **Password reset tokens** — short TTL, single use
3. **Input validation** — parameterized queries, escaped output, no trust in the client
4. **CORS** — locked to your own domains, never `*` in production
5. **Rate limiting** — especially on login, reset, signup, and anything expensive
6. **Error handling** — custom pages, no stack traces leaking to users
7. **Database indexes** — targeted on hot queries, not on every column
8. **Logging and monitoring** — structured logs plus alerts on critical failures
9. **Rollback plan** — blue-green or equivalent, tested before you need it

If any item is a "we'll do it later," that's the one that breaks first.
