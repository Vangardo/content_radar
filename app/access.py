"""Revocable personal API tokens; plaintext is returned only on creation."""

import hashlib
import secrets
import time
import uuid


class AccessTokens:
    def __init__(self, store):
        self.store = store

    def create(self, name, scope, days=90, owner="admin"):
        token = "radar_" + secrets.token_urlsafe(32)
        ident = uuid.uuid4().hex
        with self.store.connect() as c:
            c.execute(
                "INSERT INTO app_access_tokens VALUES (?,?,?,?,?,?,?,0)",
                (
                    ident,
                    owner,
                    name,
                    hashlib.sha256(token.encode()).hexdigest(),
                    scope,
                    time.time(),
                    time.time() + days * 86400,
                ),
            )
        return {"id": ident, "token": token, "scope": scope}

    def verify(self, token):
        if not token or len(token) > 200:
            return None
        with self.store.connect() as c:
            r = c.execute(
                "SELECT t.owner_id,t.scope FROM app_access_tokens t JOIN app_users u ON u.id=t.owner_id WHERE t.token_hash=? AND t.revoked=0 AND t.expires_at>? AND u.disabled=0",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            ).fetchone()
        return dict(r) if r else None

    def list(self, owner="admin"):
        with self.store.connect() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT id,name,scope,created_at,expires_at,revoked FROM app_access_tokens WHERE owner_id=? ORDER BY created_at DESC",
                    (owner,),
                )
            ]

    def revoke(self, ident, owner="admin"):
        with self.store.connect() as c:
            c.execute(
                "UPDATE app_access_tokens SET revoked=1 WHERE id=? AND owner_id=?",
                (ident, owner),
            )
