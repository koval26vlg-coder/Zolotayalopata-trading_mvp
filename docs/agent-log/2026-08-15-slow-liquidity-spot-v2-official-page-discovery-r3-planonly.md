# 2026-08-15 — spot v2 official-page discovery r3 PlanOnly

r1/r2 не повторялись. Сеть не открывалась.

## Почему не Bing
- r2: 18/18 LISTED, Bing = 0 official URL
- topology v4: `https://www.mexc.com/support/articles/` = HTTP 308
- В репо реальные MEXC listing URL: `/announcements/article/...`
- Frozen identity consumer по-прежнему принимает только `/support/articles/`

## r3
- Official sitemap: MEXC `support/sitemap-index.xml`, Gate `sitemap-announcement-001.xml`
- Venue search: `/announcements?keyword=<BASE>`
- Per-symbol metadata как в r2
- MEXC announcement prefix — discovery-only, не identity verdict
- `plan_hash=fa527d7fcb2e01b56c1bf33f5d897e8c8ef69758b9f00963c0c1181da7658631`
- `plan_file_sha256=d14caf3556fa6707e8969263f878159a4a927e0e130577f0250bacec42b914f8`
