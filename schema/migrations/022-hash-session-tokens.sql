-- Sessietokens worden voortaan als SHA-256-digest opgeslagen (zie core/auth.py).
-- Bestaande plaintext-tokens eenmalig hashen zodat lopende sessies blijven werken.
-- Idempotent: een sha256-hexdigest is altijd exact 64 tekens; token_urlsafe(32)
-- is 43 tekens, dus al-gehashte rijen worden overgeslagen.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

UPDATE sessions
SET token = encode(digest(token, 'sha256'), 'hex')
WHERE length(token) <> 64;
