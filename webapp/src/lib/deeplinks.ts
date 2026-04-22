/** Deeplink builders for importing subscription URL into VPN clients. */

export interface Deeplink {
  label: string;
  url: string;
}

const enc = encodeURIComponent;

export function buildDeeplinks(urls: {
  v2ray: string;
  clash: string;
  singbox: string;
  surge: string;
  raw: string;
}): Deeplink[] {
  return [
    {
      label: "Открыть в v2rayNG",
      url: `v2rayng://install-sub/?url=${enc(urls.v2ray)}&name=Vlessich`,
    },
    {
      label: "Открыть в Clash",
      url: `clash://install-config?url=${enc(urls.clash)}&name=Vlessich`,
    },
    {
      label: "Открыть в sing-box",
      url: `sing-box://import-remote-profile?url=${enc(urls.singbox)}&name=Vlessich`,
    },
    {
      label: "Открыть в Surge",
      url: `surge:///install-config?url=${enc(urls.surge)}`,
    },
  ];
}
