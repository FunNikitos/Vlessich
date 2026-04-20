/**
 * =============================================================================
 * Vlessich — Subscription Worker
 * =============================================================================
 * Route:  sub.example.com/*
 *
 * Что делает:
 *   1. Принимает запрос пользователя с URL вида:
 *        https://sub.<domain>/<sub_url_token>?routing=smart&adblock=on&client=<name>
 *   2. Проверяет токен (валиден 64 hex chars, rate-limit по IP).
 *   3. Прокси-дёргает backend (api.<domain>/internal/sub/<token>)
 *      с секретом BACKEND_SECRET (HMAC-подпись).
 *   4. Бэкенд возвращает JSON с массивом inbound'ов
 *      (VLESS+Reality+XHTTP H3/H2/Vision + Hysteria2 + опц. MTProto).
 *   5. Worker конвертирует JSON в формат, ожидаемый клиентом:
 *        - Hiddify/Clash/Mihomo YAML    (?client=clash)
 *        - sing-box JSON                 (?client=singbox)
 *        - V2Ray base64-legacy           (?client=v2ray или по умолчанию)
 *        - Surge/Loon                    (?client=surge)
 *   6. Кеширует ответ в Cache API на 5 минут (снижает нагрузку на backend).
 *   7. Логирует метрики (без PII) — IP только как sha256(ip+salt).
 *
 * Secrets (bindings):
 *   - BACKEND_URL     : https://api.<domain>/internal/sub
 *   - BACKEND_SECRET  : shared secret для HMAC заголовка X-Vlessich-Sig
 *   - IP_SALT         : соль для sha256-хэширования IP в логах
 *
 * Rate-limit: Cloudflare Rate-Limiting rule в cloudflare.tf уже покрывает
 *             /activate и /trial; здесь доп. soft-лимит через KV (опционально).
 * =============================================================================
 */

export default {
	/**
	 * @param {Request} request
	 * @param {{ BACKEND_URL: string, BACKEND_SECRET: string, IP_SALT: string }} env
	 * @param {ExecutionContext} ctx
	 */
	async fetch(request, env, ctx) {
		const url = new URL(request.url);

		// ---- Routing -------------------------------------------------------
		if (url.pathname === "/" || url.pathname === "/robots.txt") {
			return new Response("User-agent: *\nDisallow: /\n", {
				headers: { "content-type": "text/plain", "x-robots-tag": "noindex, nofollow" },
			});
		}
		if (url.pathname === "/healthz") {
			return new Response("ok", { status: 200 });
		}
		if (request.method !== "GET") {
			return new Response("Method Not Allowed", { status: 405 });
		}

		// ---- Token extraction & validation --------------------------------
		// URL format: /<token> or /<token>/<client>
		const match = url.pathname.match(/^\/([a-f0-9]{32,128})(?:\/([a-z0-9-]+))?$/i);
		if (!match) {
			return notFound();
		}
		const token = match[1].toLowerCase();
		const clientFromPath = match[2];
		const client = (url.searchParams.get("client") || clientFromPath || detectClient(request) || "v2ray").toLowerCase();

		const routing = url.searchParams.get("routing") === "off" ? "off" : "smart";
		const adblock = url.searchParams.get("adblock") === "off" ? "off" : "on";

		// ---- Cache -------------------------------------------------------
		const cacheKey = new Request(
			`https://cache.internal/sub?t=${token}&c=${client}&r=${routing}&a=${adblock}`,
			{ method: "GET" }
		);
		const cache = caches.default;
		let cached = await cache.match(cacheKey);
		if (cached) {
			return withCommonHeaders(cached.clone(), { "x-cache": "HIT", "x-client": client });
		}

		// ---- Fetch from backend -------------------------------------------
		const ipRaw = request.headers.get("cf-connecting-ip") || "0.0.0.0";
		const ipHash = await sha256Hex(`${ipRaw}${env.IP_SALT}`);
		const country = request.cf?.country ?? "??";

		const ts = Math.floor(Date.now() / 1000).toString();
		const sig = await hmacSha256Hex(env.BACKEND_SECRET, `${token}.${ts}`);

		const backendResp = await fetch(`${env.BACKEND_URL}/${token}`, {
			method: "GET",
			cf: { cacheEverything: false },
			headers: {
				"x-vlessich-sig": sig,
				"x-vlessich-ts": ts,
				"x-vlessich-ip-hash": ipHash,
				"x-vlessich-country": country,
				"x-vlessich-client": client,
				"x-vlessich-routing": routing,
				"x-vlessich-adblock": adblock,
				"accept": "application/json",
			},
		});

		if (backendResp.status === 404) return notFound();
		if (backendResp.status === 410) return subscriptionRevoked();
		if (backendResp.status === 429) return tooManyRequests();
		if (!backendResp.ok) return backendError(backendResp.status);

		/** @type {SubscriptionPayload} */
		const payload = await backendResp.json();

		// ---- Convert to requested format -----------------------------------
		let body;
		let contentType;
		switch (client) {
			case "clash":
			case "mihomo":
			case "stash":
				body = toClashYaml(payload);
				contentType = "text/yaml; charset=utf-8";
				break;
			case "singbox":
			case "sing-box":
			case "hiddify":
				body = JSON.stringify(toSingBox(payload), null, 2);
				contentType = "application/json; charset=utf-8";
				break;
			case "surge":
				body = toSurgeConf(payload);
				contentType = "text/plain; charset=utf-8";
				break;
			case "v2ray":
			case "v2rayng":
			case "v2raytun":
			case "nekobox":
			case "streisand":
			default:
				body = toV2RayBase64(payload);
				contentType = "text/plain; charset=utf-8";
		}

		const response = new Response(body, {
			status: 200,
			headers: {
				"content-type": contentType,
				"subscription-userinfo": buildUserInfoHeader(payload),
				"profile-title": `Vlessich · ${payload.plan ?? "VPN"}`,
				"profile-update-interval": "6",
				"support-url": `https://t.me/${payload.admin_username ?? "vlessich_admin"}`,
				"x-cache": "MISS",
				"x-client": client,
			},
		});

		// Cache 5 minutes
		ctx.waitUntil(cache.put(cacheKey, response.clone()));
		return withCommonHeaders(response);
	},
};

/* =========================================================================
 *  Helpers
 * =======================================================================*/

/**
 * @typedef {Object} InboundNode
 * @property {'vless' | 'hysteria2' | 'mtproto'} protocol
 * @property {string} tag
 * @property {string} host
 * @property {number} port
 * @property {string} [uuid]
 * @property {'reality' | 'tls'} [security]
 * @property {'xhttp' | 'tcp'} [network]
 * @property {'stream-one' | 'packet-up'} [xhttpMode]
 * @property {string} [xhttpPath]
 * @property {string} [xhttpHost]
 * @property {string} [flow]
 * @property {string} [sni]
 * @property {string} [publicKey]
 * @property {string} [shortId]
 * @property {string} [password]
 * @property {string} [obfsPassword]
 * @property {string} [fingerprint]
 */

/**
 * @typedef {Object} SubscriptionPayload
 * @property {string} sub_url_token
 * @property {string} plan
 * @property {string} [admin_username]
 * @property {number} [expires_at]       Unix seconds
 * @property {number} [traffic_used_gb]
 * @property {number} [traffic_limit_gb] nullable
 * @property {number} [devices_limit]
 * @property {InboundNode[]} inbounds
 * @property {object} [routing]          routing rules from backend
 */

function detectClient(request) {
	const ua = (request.headers.get("user-agent") || "").toLowerCase();
	if (ua.includes("clash") || ua.includes("mihomo") || ua.includes("stash")) return "clash";
	if (ua.includes("hiddify") || ua.includes("sing-box")) return "singbox";
	if (ua.includes("surge") || ua.includes("loon")) return "surge";
	if (ua.includes("v2ray") || ua.includes("shadowrocket")) return "v2ray";
	return null;
}

function withCommonHeaders(response, extra = {}) {
	const headers = new Headers(response.headers);
	headers.set("cache-control", "public, max-age=300");
	headers.set("x-robots-tag", "noindex, nofollow");
	headers.set("x-content-type-options", "nosniff");
	headers.set("referrer-policy", "no-referrer");
	headers.set("strict-transport-security", "max-age=31536000; includeSubDomains; preload");
	for (const [k, v] of Object.entries(extra)) headers.set(k, String(v));
	return new Response(response.body, { status: response.status, headers });
}

function buildUserInfoHeader(p) {
	// Формат по стандарту https://github.com/XTLS/Xray-core/issues/2139
	const upload = 0;
	const download = Math.round((p.traffic_used_gb ?? 0) * 1024 ** 3);
	const total = p.traffic_limit_gb ? Math.round(p.traffic_limit_gb * 1024 ** 3) : 0;
	const expire = p.expires_at ?? 0;
	return `upload=${upload}; download=${download}; total=${total}; expire=${expire}`;
}

/* ---------- Format converters ------------------------------------------ */

function toV2RayBase64(p) {
	/** @type {string[]} */
	const uris = [];
	for (const inb of p.inbounds) {
		if (inb.protocol === "vless") uris.push(buildVlessUri(inb, p));
		else if (inb.protocol === "hysteria2") uris.push(buildHy2Uri(inb, p));
		else if (inb.protocol === "mtproto") uris.push(buildMtProtoComment(inb));
	}
	return btoa(uris.join("\n"));
}

function buildVlessUri(inb, p) {
	const params = new URLSearchParams();
	params.set("security", inb.security || "reality");
	params.set("sni", inb.sni || inb.xhttpHost || "www.microsoft.com");
	params.set("fp", inb.fingerprint || "chrome");
	if (inb.publicKey) params.set("pbk", inb.publicKey);
	if (inb.shortId) params.set("sid", inb.shortId);
	if (inb.network === "xhttp") {
		params.set("type", "xhttp");
		if (inb.xhttpMode) params.set("mode", inb.xhttpMode);
		if (inb.xhttpPath) params.set("path", inb.xhttpPath);
		if (inb.xhttpHost) params.set("host", inb.xhttpHost);
	} else {
		params.set("type", inb.network || "tcp");
		if (inb.flow) params.set("flow", inb.flow);
	}
	const fragment = encodeURIComponent(`${p.plan} · ${inb.tag}`);
	return `vless://${inb.uuid}@${inb.host}:${inb.port}?${params.toString()}#${fragment}`;
}

function buildHy2Uri(inb, p) {
	const params = new URLSearchParams();
	params.set("sni", inb.sni || "www.microsoft.com");
	if (inb.obfsPassword) {
		params.set("obfs", "salamander");
		params.set("obfs-password", inb.obfsPassword);
	}
	const fragment = encodeURIComponent(`${p.plan} · ${inb.tag}`);
	return `hysteria2://${encodeURIComponent(inb.password)}@${inb.host}:${inb.port}?${params.toString()}#${fragment}`;
}

function buildMtProtoComment(inb) {
	// v2ray клиенты не поддерживают MTProto; добавляем как комментарий-подсказку.
	// Для MTProto основной deep-link выдаётся в Telegram-боте (tg://proxy?...).
	return `# MTProto: tg://proxy?server=${inb.host}&port=${inb.port}&secret=${inb.password}`;
}

function toClashYaml(p) {
	const proxies = [];
	const proxyNames = [];

	for (const inb of p.inbounds) {
		if (inb.protocol !== "vless" && inb.protocol !== "hysteria2") continue;
		const name = `Vlessich-${inb.tag}`;
		proxyNames.push(name);

		if (inb.protocol === "vless") {
			const proxy = {
				name,
				type: "vless",
				server: inb.host,
				port: inb.port,
				uuid: inb.uuid,
				network: inb.network === "xhttp" ? "xhttp" : "tcp",
				tls: true,
				"client-fingerprint": inb.fingerprint || "chrome",
				servername: inb.sni || inb.xhttpHost || "www.microsoft.com",
				"reality-opts": {
					"public-key": inb.publicKey,
					"short-id": inb.shortId || "",
				},
				udp: true,
			};
			if (inb.flow) proxy.flow = inb.flow;
			if (inb.network === "xhttp") {
				proxy["xhttp-opts"] = {
					mode: inb.xhttpMode || "stream-one",
					path: inb.xhttpPath || "/",
					host: inb.xhttpHost || "www.microsoft.com",
				};
			}
			proxies.push(proxy);
		} else {
			proxies.push({
				name,
				type: "hysteria2",
				server: inb.host,
				port: inb.port,
				password: inb.password,
				sni: inb.sni || "www.microsoft.com",
				obfs: inb.obfsPassword ? "salamander" : undefined,
				"obfs-password": inb.obfsPassword || undefined,
				up: "100 Mbps",
				down: "500 Mbps",
			});
		}
	}

	const yaml = [
		`# Vlessich · ${p.plan} · generated at ${new Date().toISOString()}`,
		`mixed-port: 7890`,
		`allow-lan: false`,
		`mode: rule`,
		`log-level: warning`,
		`ipv6: true`,
		`dns:`,
		`  enable: true`,
		`  listen: 0.0.0.0:1053`,
		`  nameserver:`,
		`    - https://dns.cloudflare.com/dns-query`,
		`    - https://dns.quad9.net/dns-query`,
		``,
		`proxies:`,
		...proxies.map((pr) => `  - ${JSON.stringify(pr)}`),
		``,
		`proxy-groups:`,
		`  - name: "🚀 Proxy"`,
		`    type: select`,
		`    proxies: [${proxyNames.map((n) => `"${n}"`).join(", ")}, "♻️ Auto", DIRECT]`,
		`  - name: "♻️ Auto"`,
		`    type: url-test`,
		`    url: "http://cp.cloudflare.com/generate_204"`,
		`    interval: 300`,
		`    tolerance: 50`,
		`    proxies: [${proxyNames.map((n) => `"${n}"`).join(", ")}]`,
		``,
		`rules:`,
		`  - GEOSITE,category-ads-all,REJECT`,
		`  - GEOSITE,category-ru,DIRECT`,
		`  - GEOIP,RU,DIRECT`,
		`  - GEOIP,private,DIRECT,no-resolve`,
		`  - MATCH,🚀 Proxy`,
	].join("\n");

	return yaml;
}

function toSingBox(p) {
	const outbounds = [];
	const proxyTags = [];

	for (const inb of p.inbounds) {
		if (inb.protocol !== "vless" && inb.protocol !== "hysteria2") continue;
		const tag = `vlessich-${inb.tag}`;
		proxyTags.push(tag);

		if (inb.protocol === "vless") {
			const o = {
				type: "vless",
				tag,
				server: inb.host,
				server_port: inb.port,
				uuid: inb.uuid,
				flow: inb.flow || "",
				tls: {
					enabled: true,
					server_name: inb.sni || inb.xhttpHost || "www.microsoft.com",
					utls: { enabled: true, fingerprint: inb.fingerprint || "chrome" },
					reality: {
						enabled: true,
						public_key: inb.publicKey,
						short_id: inb.shortId || "",
					},
				},
			};
			if (inb.network === "xhttp") {
				o.transport = {
					type: "xhttp",
					mode: inb.xhttpMode || "stream-one",
					path: inb.xhttpPath || "/",
					host: inb.xhttpHost || "www.microsoft.com",
				};
			}
			outbounds.push(o);
		} else {
			outbounds.push({
				type: "hysteria2",
				tag,
				server: inb.host,
				server_port: inb.port,
				password: inb.password,
				obfs: inb.obfsPassword
					? { type: "salamander", password: inb.obfsPassword }
					: undefined,
				tls: {
					enabled: true,
					server_name: inb.sni || "www.microsoft.com",
				},
			});
		}
	}

	// Meta outbounds
	outbounds.push({ type: "direct", tag: "direct" });
	outbounds.push({ type: "block", tag: "block" });
	outbounds.push({ type: "dns", tag: "dns-out" });
	outbounds.unshift({
		type: "selector",
		tag: "🚀 proxy",
		outbounds: [...proxyTags, "♻️ auto"],
		default: proxyTags[0],
	});
	outbounds.unshift({
		type: "urltest",
		tag: "♻️ auto",
		outbounds: proxyTags,
		url: "https://www.gstatic.com/generate_204",
		interval: "5m",
		tolerance: 50,
	});

	return {
		log: { level: "warn", timestamp: true },
		dns: {
			servers: [
				{ tag: "cf", address: "https://dns.cloudflare.com/dns-query" },
				{ tag: "local", address: "local", detour: "direct" },
			],
			rules: [
				{ geosite: ["category-ru"], server: "local" },
			],
			strategy: "prefer_ipv4",
		},
		inbounds: [
			{ type: "tun", tag: "tun-in", inet4_address: "172.19.0.1/30", auto_route: true, strict_route: true, mtu: 1420, stack: "system", sniff: true },
		],
		outbounds,
		route: {
			rules: [
				{ protocol: "dns", outbound: "dns-out" },
				{ geosite: ["category-ads-all"], outbound: "block" },
				{ geosite: ["category-ru"], outbound: "direct" },
				{ geoip: ["ru", "private"], outbound: "direct" },
			],
			final: "🚀 proxy",
			auto_detect_interface: true,
		},
	};
}

function toSurgeConf(p) {
	const proxies = [];
	for (const inb of p.inbounds) {
		if (inb.protocol !== "vless") continue; // Surge VLESS-only in this simplified
		const line = `Vlessich-${inb.tag} = vless, ${inb.host}, ${inb.port}, username=${inb.uuid}, tls=true, sni=${inb.sni || "www.microsoft.com"}, reality-public-key=${inb.publicKey}, reality-short-id=${inb.shortId || ""}`;
		proxies.push(line);
	}
	return [
		`# Vlessich · ${p.plan}`,
		`[Proxy]`,
		...proxies,
		`[Proxy Group]`,
		`Vlessich = select, ${proxies.map((x) => x.split(" = ")[0]).join(", ")}`,
		`[Rule]`,
		`GEOIP,RU,DIRECT`,
		`FINAL,Vlessich`,
	].join("\n");
}

/* ---------- Crypto helpers --------------------------------------------- */

async function sha256Hex(input) {
	const data = new TextEncoder().encode(input);
	const buf = await crypto.subtle.digest("SHA-256", data);
	return bufToHex(buf);
}

async function hmacSha256Hex(secret, message) {
	const key = await crypto.subtle.importKey(
		"raw",
		new TextEncoder().encode(secret),
		{ name: "HMAC", hash: "SHA-256" },
		false,
		["sign"]
	);
	const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
	return bufToHex(sig);
}

function bufToHex(buf) {
	return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/* ---------- Error responses ------------------------------------------- */

function notFound() {
	return new Response("Not Found", { status: 404, headers: { "x-robots-tag": "noindex" } });
}
function subscriptionRevoked() {
	return new Response("Subscription revoked. Contact support.", { status: 410 });
}
function tooManyRequests() {
	return new Response("Too Many Requests", { status: 429, headers: { "retry-after": "60" } });
}
function backendError(status) {
	return new Response(`Backend error (${status})`, { status: 502 });
}
