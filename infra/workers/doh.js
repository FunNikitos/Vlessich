/**
 * Vlessich — DoH (DNS-over-HTTPS) edge Worker
 * ----------------------------------------------------------------------------
 * Route:   dns.<domain>/dns-query*
 * Spec:    RFC 8484 (application/dns-message), RFC 8427 (application/dns-json)
 *
 * Behaviour:
 *   - Accepts GET (?dns=<base64url>) and POST (Content-Type: application/dns-message).
 *   - Optional JSON API: GET ?name=<fqdn>&type=<rrtype>  (Content-Type: application/dns-json).
 *   - Forwards queries to upstream resolver (default: Cloudflare 1.1.1.1 DoH).
 *   - Returns binary DNS response with proper TTL-aware Cache-Control.
 *   - Adblock: optional NXDOMAIN for domains in BLOCKLIST_KV (KV namespace).
 *   - Zero PII logging (only sha256(ip + IP_SALT) for abuse rate-limiting hooks).
 *
 * Bindings (configure in cloudflare.tf / wrangler.toml):
 *   UPSTREAM_DOH    (var)    — default "https://cloudflare-dns.com/dns-query"
 *   FALLBACK_DOH    (var)    — default "https://dns.quad9.net/dns-query"
 *   IP_SALT         (secret) — random 32+ bytes hex
 *   BLOCKLIST_KV    (KV, optional) — keys = lowercased FQDN, value = "1"
 *   ENABLE_ADBLOCK  (var)    — "1" to enable BLOCKLIST_KV lookups (default off)
 *
 * Hard rules:
 *   - No request/response body logging.
 *   - No query name leakage to logs (only opaque hash for metrics).
 *   - Reject oversized payloads (>4 KiB).
 */

const MAX_DNS_MSG_BYTES = 4096;
const DEFAULT_UPSTREAM = "https://cloudflare-dns.com/dns-query";
const DEFAULT_FALLBACK = "https://dns.quad9.net/dns-query";
const UPSTREAM_TIMEOUT_MS = 4000;

export default {
  /**
   * @param {Request} request
   * @param {{
   *   UPSTREAM_DOH?: string,
   *   FALLBACK_DOH?: string,
   *   IP_SALT?: string,
   *   BLOCKLIST_KV?: KVNamespace,
   *   ENABLE_ADBLOCK?: string
   * }} env
   * @param {ExecutionContext} ctx
   */
  async fetch(request, env, ctx) {
    try {
      const url = new URL(request.url);

      // Health-check / liveness
      if (url.pathname === "/healthz") {
        return new Response("ok", { status: 200, headers: { "cache-control": "no-store" } });
      }

      if (url.pathname !== "/dns-query") {
        return new Response("not found", { status: 404 });
      }

      // CORS preflight (для DoH-клиентов в браузере, e.g. Firefox TRR test pages)
      if (request.method === "OPTIONS") {
        return new Response(null, {
          status: 204,
          headers: corsHeaders(request),
        });
      }

      if (request.method !== "GET" && request.method !== "POST") {
        return new Response("method not allowed", {
          status: 405,
          headers: { allow: "GET, POST, OPTIONS" },
        });
      }

      // JSON API (?name=&type=) — application/dns-json
      const acceptsJson =
        url.searchParams.has("name") ||
        (request.headers.get("accept") || "").includes("application/dns-json");

      if (acceptsJson && request.method === "GET") {
        return proxyJson(url, env, request);
      }

      // Wire-format DNS message
      const dnsMessage = await readDnsMessage(request, url);
      if (!dnsMessage) {
        return new Response("bad request", { status: 400 });
      }
      if (dnsMessage.byteLength > MAX_DNS_MSG_BYTES) {
        return new Response("payload too large", { status: 413 });
      }

      // Adblock — best-effort, не ломаем запрос если KV недоступен
      if (env.ENABLE_ADBLOCK === "1" && env.BLOCKLIST_KV) {
        const qname = parseFirstQName(dnsMessage);
        if (qname && (await isBlocked(qname, env.BLOCKLIST_KV))) {
          const nx = buildNxResponse(dnsMessage);
          return new Response(nx, {
            status: 200,
            headers: dnsResponseHeaders(60, request),
          });
        }
      }

      // Forward to upstream (с фолбэком)
      const upstream = env.UPSTREAM_DOH || DEFAULT_UPSTREAM;
      const fallback = env.FALLBACK_DOH || DEFAULT_FALLBACK;

      let upstreamRes = await forward(upstream, dnsMessage);
      if (!upstreamRes || !upstreamRes.ok) {
        upstreamRes = await forward(fallback, dnsMessage);
      }
      if (!upstreamRes || !upstreamRes.ok) {
        return new Response("upstream unavailable", { status: 502 });
      }

      const body = await upstreamRes.arrayBuffer();
      const ttl = clampTtl(extractMinTtl(new Uint8Array(body)));

      return new Response(body, {
        status: 200,
        headers: dnsResponseHeaders(ttl, request),
      });
    } catch (err) {
      // Никаких деталей наружу.
      return new Response("internal error", { status: 500 });
    }
  },
};

// ---------------------------------------------------------------------------
// Request parsing
// ---------------------------------------------------------------------------

/**
 * @param {Request} request
 * @param {URL} url
 * @returns {Promise<Uint8Array | null>}
 */
async function readDnsMessage(request, url) {
  if (request.method === "GET") {
    const dns = url.searchParams.get("dns");
    if (!dns) return null;
    try {
      return base64UrlDecode(dns);
    } catch {
      return null;
    }
  }
  // POST
  const ct = (request.headers.get("content-type") || "").toLowerCase();
  if (!ct.includes("application/dns-message")) return null;
  const buf = await request.arrayBuffer();
  if (!buf || buf.byteLength === 0) return null;
  return new Uint8Array(buf);
}

/**
 * Forward wire-format DNS message to upstream DoH endpoint.
 * @param {string} endpoint
 * @param {Uint8Array} message
 * @returns {Promise<Response | null>}
 */
async function forward(endpoint, message) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: {
        "content-type": "application/dns-message",
        "accept": "application/dns-message",
      },
      body: message,
      signal: controller.signal,
      // CF-specific: дать рантайму закэшировать на edge
      cf: { cacheTtl: 60, cacheEverything: false },
    });
    return res;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Proxy JSON DoH (application/dns-json) — для совместимости с web-клиентами.
 * @param {URL} url
 * @param {object} env
 * @param {Request} request
 */
async function proxyJson(url, env, request) {
  const upstream = (env.UPSTREAM_DOH || DEFAULT_UPSTREAM).replace(/\/dns-query$/, "/dns-query");
  const target = new URL(upstream);
  // Прокидываем разрешённые параметры
  const allowed = ["name", "type", "ct", "do", "cd"];
  for (const k of allowed) {
    const v = url.searchParams.get(k);
    if (v !== null) target.searchParams.set(k, v);
  }
  // Принудительно application/dns-json
  target.searchParams.set("ct", "application/dns-json");

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);
  try {
    const res = await fetch(target.toString(), {
      method: "GET",
      headers: { accept: "application/dns-json" },
      signal: controller.signal,
      cf: { cacheTtl: 60, cacheEverything: false },
    });
    if (!res.ok) {
      return new Response("upstream unavailable", { status: 502 });
    }
    const body = await res.arrayBuffer();
    return new Response(body, {
      status: 200,
      headers: {
        "content-type": "application/dns-json",
        "cache-control": "public, max-age=60",
        ...corsHeaders(request),
      },
    });
  } catch {
    return new Response("upstream unavailable", { status: 502 });
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// DNS wire-format helpers
// ---------------------------------------------------------------------------

/**
 * Парсит первый QNAME из DNS-сообщения. Возвращает lowercased FQDN без trailing dot.
 * @param {Uint8Array} msg
 * @returns {string | null}
 */
function parseFirstQName(msg) {
  // Header = 12 bytes; QDCOUNT at offset 4..5.
  if (msg.length < 13) return null;
  const qdcount = (msg[4] << 8) | msg[5];
  if (qdcount < 1) return null;

  let off = 12;
  const labels = [];
  let safety = 0;
  while (off < msg.length && safety++ < 128) {
    const len = msg[off];
    if (len === 0) {
      off += 1;
      break;
    }
    // Compression pointers не должны встречаться в QNAME, но защитимся.
    if ((len & 0xc0) === 0xc0) return null;
    if (len > 63) return null;
    if (off + 1 + len > msg.length) return null;
    const label = new TextDecoder("utf-8", { fatal: false }).decode(
      msg.subarray(off + 1, off + 1 + len)
    );
    labels.push(label.toLowerCase());
    off += 1 + len;
  }
  if (labels.length === 0) return null;
  return labels.join(".");
}

/**
 * Строит ответ NXDOMAIN на базе входящего запроса (копирует header+question, выставляет RCODE=3).
 * @param {Uint8Array} req
 * @returns {Uint8Array}
 */
function buildNxResponse(req) {
  // Найти конец секции Question
  if (req.length < 13) return req;
  let off = 12;
  let safety = 0;
  while (off < req.length && safety++ < 128) {
    const len = req[off];
    if (len === 0) {
      off += 1;
      break;
    }
    if ((len & 0xc0) === 0xc0) {
      off += 2;
      break;
    }
    off += 1 + len;
  }
  // QTYPE(2) + QCLASS(2)
  off += 4;
  const out = new Uint8Array(off);
  out.set(req.subarray(0, off));
  // Flags: QR=1, Opcode=0, AA=0, TC=0, RD=copied, RA=1, RCODE=3 (NXDOMAIN)
  const rd = req[2] & 0x01;
  out[2] = 0x80 | rd; // QR + RD
  out[3] = 0x80 | 0x03; // RA + RCODE=3
  // ANCOUNT/NSCOUNT/ARCOUNT = 0
  out[6] = 0; out[7] = 0;
  out[8] = 0; out[9] = 0;
  out[10] = 0; out[11] = 0;
  return out;
}

/**
 * Грубая оценка минимального TTL ответа: ищем первое RR в Answer и берём его TTL.
 * Возвращает 0 если не удалось.
 * @param {Uint8Array} msg
 */
function extractMinTtl(msg) {
  if (msg.length < 13) return 0;
  const ancount = (msg[6] << 8) | msg[7];
  if (ancount < 1) return 0;

  // Skip header
  let off = 12;
  // Skip QDCOUNT questions
  const qdcount = (msg[4] << 8) | msg[5];
  for (let i = 0; i < qdcount && off < msg.length; i++) {
    off = skipName(msg, off);
    if (off < 0) return 0;
    off += 4; // QTYPE+QCLASS
  }
  // First Answer RR
  off = skipName(msg, off);
  if (off < 0 || off + 10 > msg.length) return 0;
  // TYPE(2) CLASS(2) TTL(4) RDLENGTH(2)
  const ttl =
    (msg[off + 4] << 24) |
    (msg[off + 5] << 16) |
    (msg[off + 6] << 8) |
    msg[off + 7];
  return ttl >>> 0;
}

/** Возвращает offset после имени. Поддерживает compression pointers. */
function skipName(msg, off) {
  let safety = 0;
  while (off < msg.length && safety++ < 128) {
    const len = msg[off];
    if (len === 0) return off + 1;
    if ((len & 0xc0) === 0xc0) return off + 2;
    if (len > 63) return -1;
    off += 1 + len;
  }
  return -1;
}

function clampTtl(ttl) {
  if (!Number.isFinite(ttl) || ttl <= 0) return 60;
  if (ttl > 3600) return 3600;
  if (ttl < 30) return 30;
  return ttl;
}

// ---------------------------------------------------------------------------
// Adblock
// ---------------------------------------------------------------------------

/**
 * Проверяет домен и его родительские зоны в KV.
 * Хранение: ключ = "ads.example.com" → "1".
 * Совпадение по поддоменам: ищем foo.bar.baz, потом bar.baz, потом baz.
 */
async function isBlocked(qname, kv) {
  const parts = qname.split(".");
  for (let i = 0; i < parts.length - 1; i++) {
    const candidate = parts.slice(i).join(".");
    try {
      const v = await kv.get(candidate);
      if (v === "1") return true;
    } catch {
      return false;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function dnsResponseHeaders(ttl, request) {
  return {
    "content-type": "application/dns-message",
    "cache-control": `public, max-age=${ttl}`,
    "x-content-type-options": "nosniff",
    ...corsHeaders(request),
  };
}

function corsHeaders(request) {
  const origin = request.headers.get("origin") || "*";
  return {
    "access-control-allow-origin": origin,
    "access-control-allow-methods": "GET, POST, OPTIONS",
    "access-control-allow-headers": "content-type, accept",
    "access-control-max-age": "86400",
  };
}

// ---------------------------------------------------------------------------
// base64url
// ---------------------------------------------------------------------------

function base64UrlDecode(input) {
  // RFC 4648 §5 (URL-safe, без padding)
  let s = input.replace(/-/g, "+").replace(/_/g, "/");
  const pad = s.length % 4;
  if (pad === 2) s += "==";
  else if (pad === 3) s += "=";
  else if (pad === 1) throw new Error("invalid base64url length");
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
