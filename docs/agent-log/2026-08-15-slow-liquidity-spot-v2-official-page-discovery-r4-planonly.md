# 2026-08-15 — spot v2 official-page discovery r4 PlanOnly

r3 не повторялся. Сеть не открывалась.

## Почему не r3
- 18/18 LISTED
- Support sitemap + `/announcements?keyword=` = 0 official URL
- Numeric loc без title не биндит тикер

## r4
- MEXC `news/sitemap-index.xml` (не support)
- Gate `sitemap-google-news-recent-en-001.xml` + announcement sitemap
- Match: `news:title` / `image:title` / loc slug
- Locator diagnostics в манифесте
- Не Bing, не HTML keyword search
- `plan_hash=2f8cb14b747e582c54b1749a5ff2f5955774b427d2792d31b3853af9c3cd5de9`
- `plan_file_sha256=05187e3be802a5f2d53d00866f342c1a3f4a0c9d29f70932831ec16973203cce`
