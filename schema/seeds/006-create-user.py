"""Create or update a Stroom login user.

Usage (inside docker, via Bash):

    docker run --rm --network personal_net \\
      -v /opt/stacks/vps-stacks/stroom-src/schema/seeds:/seeds:ro \\
      -e PGHOST=stroom-db -e PGUSER=stroom -e PGDATABASE=stroom \\
      -e PGPASSWORD=$STROOM_DB_PASSWORD \\
      -e SEED_EMAIL=han@hanrusman.nl -e SEED_PASSWORD='supersecret' \\
      python:3.12-slim sh -c "pip install -q 'psycopg[binary]' && python /seeds/006-create-user.py"
"""
import base64
import hashlib
import os
import secrets
import sys

import psycopg

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEYLEN = 64


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                       n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_KEYLEN)
    return f"scrypt${SCRYPT_N}${base64.b64encode(salt).decode()}${base64.b64encode(h).decode()}"


def main():
    email = os.environ.get("SEED_EMAIL", "").strip().lower()
    password = os.environ.get("SEED_PASSWORD", "")
    if not email or not password:
        print("Set SEED_EMAIL and SEED_PASSWORD env vars.", file=sys.stderr)
        sys.exit(2)

    dsn = (
        f"host={os.environ['PGHOST']} dbname={os.environ['PGDATABASE']} "
        f"user={os.environ['PGUSER']} password={os.environ['PGPASSWORD']}"
    )
    pwd_hash = hash_password(password)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash) VALUES (%s, %s)
                ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash
                RETURNING id, (xmax = 0) AS inserted
                """,
                (email, pwd_hash),
            )
            row = cur.fetchone()
            conn.commit()
    user_id, inserted = row
    print(f"{'Created' if inserted else 'Updated'} user {email} (id={user_id})")


if __name__ == "__main__":
    main()
