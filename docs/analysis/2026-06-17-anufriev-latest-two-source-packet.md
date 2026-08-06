# Anufriev Latest Two Shorts Source Packet

Дата: 2026-06-17  
Статус: metadata + caption-track probe. Не transcript-backed.

## Source

- RSS refresh XML: `exports/youtube-anufriev/anufriev_youtube_rss_refresh_20260617_164026.xml`
- RSS refresh CSV: `exports/youtube-anufriev/anufriev_youtube_rss_refresh_20260617_164026.csv`
- RSS delta CSV: `exports/youtube-anufriev/anufriev_youtube_rss_refresh_delta_20260617_164026.csv`
- Transcript probe JSON: `exports/youtube-anufriev/anufriev_latest_two_transcript_probe_20260617_1649.json`

## Videos

| Video ID | Title | Published | Evidence level | Project implication |
|---|---|---|---|---|
| `TkQK2Bbvdek` | `Как сейчас покупать крипту без 115 ФЗ?` | 2026-06-17 16:00:08 +03:00 | metadata + caption track found, transcript empty/blocked | Compliance / fiat rails / bank risk; not alpha |
| `m89dqFDSL2Q` | `Где безопаснее хранить крипту?` | 2026-06-17 15:00:18 +03:00 | metadata + caption track found, transcript empty/blocked | Custody / venue risk; not trading signal |

## Transcript Probe Result

Direct timedtext checks:

- `https://www.youtube.com/api/timedtext?v=<id>&lang=ru&fmt=json3`
- `https://www.youtube.com/api/timedtext?v=<id>&lang=ru&fmt=json3&kind=asr`
- `https://video.google.com/timedtext?v=<id>&lang=ru&fmt=json3`

Result:

- HTTP 200 but empty body for Russian timedtext endpoints on both videos.
- Watch pages contained `ytInitialPlayerResponse` and `captionTracks`.
- Caption tracks were visible, but `baseUrl` fetches returned empty body for Russian tracks.
- One translated English caption track check for `TkQK2Bbvdek` returned HTTP 429.

Conclusion:

- These two videos must remain `metadata-only` for claims.
- It is acceptable to use their titles as weak theme evidence.
- Do not quote or infer detailed claims from them until transcript extraction succeeds.

## Project Decision

The videos strengthen the same non-alpha layer already identified in the latest RSS delta:

- 115-ФЗ / bank risk / fiat rails are operational constraints, not bot signals.
- Custody safety is a venue/capital-management issue, not a source of win-rate.
- They support `docs/analysis/live-readiness-checklist.md`.
- They do not change the trading strategy ranking or justify live trading.

