# nucs.dev

`nucs.dev` and `www.nucs.dev` send every visit to this profile, https://github.com/Nucs, with a **temporary (302) redirect**. It has been live since 2026-10-02. Any path or query string lands on the profile page itself, so no `nucs.dev` link can end on a GitHub 404.

## How it works

- **Where the domain lives:** registered at Cloudflare Registrar, with its DNS served by Cloudflare.
- **The redirect:** a Cloudflare Single Redirect rule answers every request at Cloudflare's edge, over http and https, IPv4 and IPv6. No server of mine serves or relays it, so it works whatever state they are in.
- **Placeholder records:** both names have proxied records pointing at `192.0.2.1` and `100::`, addresses that reach nothing. They exist only so requests reach Cloudflare, where the rule answers them.
- **HTTPS:** Cloudflare's Universal SSL certificate for `nucs.dev` and `*.nucs.dev` covers it. Browsers allow only HTTPS on `.dev` (HSTS preload), so without that certificate nothing would load.
- **Why 302 and not 301:** browsers don't cache a 302. Pointing the domain somewhere else later reaches every visitor at once; a 301 would stay cached in every browser that ever saw it.

## Changing or removing it

The redirect is managed from my private homelab repository (`K:\source\proxmox`), in `cloudflare/nucs-dev/`. That folder's `README.md` has the details: the exact rule and records, credentials, and checks.

```bash
bash cloudflare/nucs-dev/redirect.sh status   # what is configured, then a live check
bash cloudflare/nucs-dev/redirect.sh verify   # live check only
bash cloudflare/nucs-dev/redirect.sh remove   # end the redirect
```

To point it somewhere else, change `TARGET_URL` at the top of `redirect.sh` and run `apply`, then update this file.
