# June — raw 2025 per-game play-by-play (Savant + MLB Stats API)

Pure data-transfer pipeline: pull raw play-by-play for every 2025 MLB regular-season
game from **two sources** and store each game in its **own schema** — strict source
fidelity, no filtering / transformation / aggregation / enrichment.

## Output
One DuckDB file: **`mlb_2025.duckdb`** with a schema per game:

```
game_<gamePk>.savant_pitches   raw Baseball Savant statcast_search
                               (every pitch, all 119 columns, original names/order,
                                stored all-VARCHAR so no value is altered)
game_<gamePk>.mlb_allplays     raw MLB Stats API feed/live play-by-play (allPlays;
                                nested pitch-by-pitch playEvents preserved inside;
                                falls back to a raw JSON blob if it won't tabularize)
```
Games with no data (postponed/suspended records) get a 1-column `no_data` table.

## Run
```bash
python ingest.py                 # all 2025 reg-season games (~2,464 records, ~2,430 with data)
python ingest.py --limit 3       # quick validation on the first 3 games
python ingest.py --db other.duckdb --sleep 0.25
```
Idempotent + **resumable**: a game whose schema already exists is skipped, so you can
stop/restart the run anytime. Full run is ~2-3 hours (one Savant + one feed fetch per game).

## Query examples
```sql
-- list game schemas
SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'game_%';

-- raw pitches for one game
SELECT * FROM "game_778563".savant_pitches;

-- pitch-by-pitch events (nested) for one game
SELECT * FROM "game_778563".mlb_allplays;
```

## Sources
- Baseball Savant: `statcast_search/csv?all=true&type=details&game_pk=<pk>` (per-pitch, 119 cols).
- MLB Stats API: `statsapi.mlb.com/api/v1.1/game/<pk>/feed/live` (liveData.plays.allPlays).
- Schedule: `statsapi.mlb.com/api/v1/schedule?sportId=1&season=2025&gameType=R`.

No keys required (both public). This is raw archival storage, not modeling.
