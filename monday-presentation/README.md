# SentinelMAS Monday Presentation

Apple-style React presentation deck for the Challenge 4 Monday pitch.

## Run

```bash
npm install
npm run dev
```

Open the local Vite URL and move through slides with the arrow keys.

## Two decks

The same app serves two presentations behind a start page:

- **Start page** — default route: `/` (logo, team, challenge, and two buttons)
- **Demo Day deck (long version)** — `/?deck=demo`
- **Wednesday pitch (5-minute, MEIA structure)** — `/?deck=pitch` (or `/#pitch`)

Eight pitch slides: Cover, Problem, Market, Solution, Intelligence, Demo, Team, Close.

> Placeholders to replace before the pitch: the MEIA/team logos (text lockup in `LogoLockup`), team member photos (currently initials avatars), and the economic figures on the Problem slide (verify/cite sources).

## Video Slots

Drop demo clips into `public/videos/` with these filenames and the deck will load them automatically:

- `sentinelmas-dashboard-demo.mp4`
- `booster-webots-demo.mp4`
