# Text-to-SQL agent on Databricks Apps

A FastAPI front end for the LangGraph agent in `main.py`. One question in, generated
SQL and rows out, with the graph's built-in retry on a failed query.

## One change you must make to `main.py`

`generate_sql_node` prints `expected_sql`, which is only defined inside the
`if __name__ == "__main__":` evaluation loop. When `main.py` is imported by the web
app instead of run directly, that name doesn't exist and every query raises
`NameError`. Delete these three lines from `generate_sql_node`:

```python
    print("\nEXPECTED SQL:")
    print(expected_sql)
```

Everything else in `main.py` works as-is — the eval harness stays guarded under
`__main__` and won't run on import.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | FastAPI app: `/` console, `POST /query`, `GET /health`, `/docs` |
| `static/index.html` | The query console |
| `app.yaml` | Databricks Apps start command and environment |
| `requirements.txt` | Dependencies, with the version floors that fix your two crashes |

Ship these alongside your existing `main.py`, `constants.py`, `db.py`,
`table_extraction_3.py`, `schema_store_retrival_2.py`, the `.db` file, the
`*_schema.txt` file, and the vector store directory.

## Run it locally first

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000. If that works, deployment is mostly file copying.

## Deploy to Databricks Apps

1. **Create the secret.**

   ```bash
   databricks secrets create-scope text-to-sql
   databricks secrets put-secret text-to-sql openai-api-key
   ```

2. **Sync the source** into your workspace, e.g.
   `/Workspace/Users/<you>/text-to-sql/`. Either use the workspace file browser or:

   ```bash
   databricks sync . /Workspace/Users/<you>/text-to-sql
   ```

   Don't upload `.env` — the key comes from the secret instead.

3. **Create the app** under Compute → Apps → Create app, custom app, pointing at
   that folder.

4. **Add the secret as a resource** in the app's Configuration tab: resource type
   Secret, scope `text-to-sql`, key `openai-api-key`, resource name
   `openai-api-key`. That name is what `valueFrom` in `app.yaml` resolves against.

5. **Deploy.** Databricks installs `requirements.txt`, then runs the `command` from
   `app.yaml`. `$DATABRICKS_APP_PORT` is substituted with the real port at runtime,
   so don't hardcode 8000 there.

6. **Check `/health`** on the app URL. It reports whether the database file was
   found and whether the API key came through, which separates a packaging problem
   from a code problem straight away.

## Things that behave differently on Databricks

**SQLite is bundled, not persistent.** The `.db` file rides along with your source
and the app container is ephemeral. Reads are fine; anything that writes will be
lost on redeploy. If you hit `attempt to write a readonly database`, copy the file
to `/tmp` at startup and point `DB_PATH` there.

**No `.env`.** `load_dotenv()` is harmless but does nothing. Every setting has to
come through `app.yaml`.

**Outbound calls to OpenAI** must be allowed by your workspace's network policy.
If requests hang or fail with a connection error and the key is set, that's the
first thing to check with your workspace admin.

**Egress-free installs.** Databricks resolves `requirements.txt` at deploy time.
Pin exact versions once your local venv works (`pip freeze > requirements.txt`) so
a fresh resolve can't hand you another mismatched pair.

## Where this should go next

SQLite bundled into an app is fine for a demo of the agent, but it means the data
is a snapshot in your source tree. The natural Databricks version is to swap
`db.py` for `databricks-sql-connector` against a SQL warehouse, and to source
`get_relevant_schema` from Unity Catalog's `information_schema` rather than a
checked-in `.txt`. Then the app has no data files at all, and the agent queries
whatever the warehouse can see.
