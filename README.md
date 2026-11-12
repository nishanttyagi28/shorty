# shorty

Small URL shortener: FastAPI on top of a single SQLite file (plain `sqlite3`,
no ORM). No auth, meant for running locally or behind something else.


Live demo: https://shorty-taupe.vercel.app

## Install

Needs Python 3.9+.

```console
git clone https://github.com/nishanttyagi28/shorty.git
cd shorty
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

## Run

```console
python -m shorty                  # serves on 127.0.0.1:8000
uvicorn shorty.app:app --reload   # or this while hacking on it
```

The database lives in `shorty.db` in the current directory. Set `SHORTY_DB`
to put it somewhere else.

## API

| Method | Path            | What it does                                   |
| ------ | --------------- | ---------------------------------------------- |
| GET    | `/health`       | health check                                   |
| GET    | `/links`        | list all links, newest first                   |
| POST   | `/links`        | create a link: `{"url": ..., "custom_code": ...}` (code optional) -> 201 |
| GET    | `/links/{code}` | stats for one link                             |
| DELETE | `/links/{code}` | delete a link -> 204                           |
| GET    | `/{code}`       | 307 redirect to the target, bumps the hit count |

- only `http`/`https` URLs are accepted, anything else is a 422
- custom codes may use letters, digits, `-` and `_`
- `health`, `links`, `docs`, `openapi.json` and `redoc` are reserved (422),
  since those paths are already taken by the app
- a custom code that's already in use gives 409, unknown codes give 404
- without a custom code you get a random 7 character one

## Example

```console
$ curl -s -X POST localhost:8000/links \
    -H 'content-type: application/json' \
    -d '{"url": "https://example.com", "custom_code": "ex"}'
{"code":"ex","url":"https://example.com","short_url":"http://localhost:8000/ex"}

$ curl -si localhost:8000/ex | head -1
HTTP/1.1 307 Temporary Redirect

$ curl -s localhost:8000/links/ex
{"code":"ex","url":"https://example.com","hits":1,"created_at":"2026-10-15T11:22:37.495930+00:00"}

$ curl -s -X POST localhost:8000/links \
    -H 'content-type: application/json' \
    -d '{"url": "https://example.com", "custom_code": "docs"}'
{"detail":[{"type":"value_error","loc":["body","custom_code"],"msg":"Value error, custom_code 'docs' is reserved","input":"docs","ctx":{"error":{}}}]}
```

## Tests

```console
pytest
```

Each test gets its own throwaway SQLite file, so your `shorty.db` is never touched.

## License

MIT
