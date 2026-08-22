---
name: add-a-setting
description: Add a user-facing setting or per-account switch to Petri Net Sim end to end, from the toggle in Settings to the code that honours it. Use when adding anything to the Settings screen, a per-user preference or permission, or when a saved setting does not survive a reload.
---

# Adding a setting

This repo has been audited once for options that read as load-bearing and did
nothing, and four were deleted. The bar since then: **a setting either changes
behaviour or it does not exist.**

## Decide where it lives

| Kind | Home | Example |
|------|------|---------|
| Deployment-wide, set by whoever runs the server | `backend/src/core/config.py` plus `.env.example` | `MCP_ENABLED`, `AUTH_MODE` |
| Per account, owned by the user | `User.metadata_`, exposed through `/api/v1/auth/me` | the MCP and API switches |
| Per browser, no server meaning | `stores/ui-store.ts` with `setItem` | theme, language, panel layout |

A per-account flag does **not** belong in localStorage. It has to be readable
by the code that enforces it, which runs on the server.

## The backend, for a per-account flag

1. A small module owning the shape and the default, like
   `services/auth/integrations.py`. Absent or malformed reads as the
   permissive default, so old accounts keep working.
2. Expose it on `UserResponse` and accept it on `UpdateProfileRequest`
   (`api/versions/v1/schemas/auth.py`). Booleans are tri-state on the wire:
   `None` means "leave alone", `False` is a value to write.
3. Merge it in `update_me` (`api/versions/v1/routers/auth.py`).
4. **Enforce it** where the behaviour happens, and return the status code that
   tells the truth. A valid key on an account that revoked a permission is
   403, not 401: another key is not the fix.

### Two traps that have already bitten

> [!WARNING]
> **Commit, or the write never happens.** `UserRepository.update` flushes; the
> session dependency does not commit on the way out. Without
> `await session.commit()` the handler returns the new value from an object
> whose transaction is about to roll back, so the API reports success and the
> row keeps its old value.

> [!WARNING]
> **Rebuild nested dicts, never edit them in place.** `dict(user.metadata_)`
> is shallow, so a nested dict inside it is the same object SQLAlchemy holds
> as the column's committed value. Mutating it moves the "before" and the
> "after" together, the flush finds nothing to write, and the change vanishes.
> The tell is distinctive: the first write works, every later one silently
> does not.

## The frontend

1. Type it on `AuthUser` (`types/auth.ts`) and on `UpdateProfilePayload`
   (`stores/auth-store.ts`).
2. Read it defensively: `user?.flag !== false` matches the server's own
   permissive default and survives an older backend.
3. Write through immediately with `updateProfile`. There is no Save button on
   that screen, so a switch that only moves on screen is a switch that lies.
   Roll the optimistic flip back if the request fails, and show the error.
4. New Settings section? Add it to `SettingsView`'s `NAV_ITEMS`, which is also
   the list of valid `/settings/:section` paths.
5. Strings go in **both** `i18n/locales/en.json` and `uk.json`.

## Prove it

```bash
uv run pytest tests/test_user_integrations.py -q --no-cov
npx vitest run src/components/settings
```

Write these three:

- **A second request.** Patch it, then re-read it in a separate request. A
  test that only checks the PATCH response passes on code that saves nothing.
- **Off and on again.** Not just the first write. This is the nested-dict trap
  above, and only a second round trip catches it.
- **A refusal.** The thing the setting forbids, actually refused, with the
  status code you promised.

Then run it for real against a live instance:

```bash
docker compose -f docker-compose.allinone.yml up -d --build
curl -s -X PATCH http://localhost:6204/api/v1/auth/me \
  -H "Content-Type: application/json" -d '{"your_flag": false}'
# now call the thing it should forbid and read the status code
```

In `single_user` mode no token is needed, which makes this a two-command
check. Revoke any API key you minted for the test when you are done.
