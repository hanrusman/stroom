#!/usr/bin/env bash
# Stroom memory/connection diagnostic — read-only.
# Bedoeld om op strongbad te draaien voordat we Kimi's "memory optimization"
# voorstellen implementeren. Geen mutaties, alleen metingen.
#
# Gebruik:
#   bash diagnose-memory.sh                     # auto-detect containers
#   API=stroom-api PG=stroom-postgres bash diagnose-memory.sh   # override
#
# Geeft output op stdout — pipe naar bestand als je wilt delen:
#   bash diagnose-memory.sh | tee /tmp/stroom-diag.txt

set -u

section() { printf '\n\n=== %s ===\n' "$*"; }
sub()     { printf '\n--- %s ---\n' "$*"; }
note()    { printf '  (%s)\n' "$*"; }

# ---------- Container auto-detect ----------
API="${API:-$(docker ps --format '{{.Names}}' | grep -E '^stroom.*api|^stroom-api' | head -1)}"
PG="${PG:-$(docker ps --format '{{.Names}}' | grep -E 'stroom.*postgres|stroom.*db|^postgres' | head -1)}"
LLM="${LLM:-$(docker ps --format '{{.Names}}' | grep -E 'litellm' | head -1)}"

section "Container detectie"
echo "API container : ${API:-NIET GEVONDEN}"
echo "Postgres      : ${PG:-NIET GEVONDEN}"
echo "LiteLLM       : ${LLM:-NIET GEVONDEN}"

if [ -z "$API" ] || [ -z "$PG" ]; then
  echo
  echo "Kan stroom containers niet vinden. Lijst alle running containers:"
  docker ps --format '  {{.Names}}\t{{.Image}}'
  echo
  echo "Override met: API=<naam> PG=<naam> bash $0"
  exit 1
fi

# ---------- 1. RAM gebruik ----------
section "1. RAM gebruik (snapshot)"
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}' \
  $API $PG ${LLM:-}

sub "Container mem limits"
for c in $API $PG ${LLM:-}; do
  [ -z "$c" ] && continue
  limit=$(docker inspect "$c" --format '{{.HostConfig.Memory}}' 2>/dev/null)
  if [ "$limit" = "0" ]; then
    printf '%-25s no limit set\n' "$c"
  else
    printf '%-25s %s bytes (%s MB)\n' "$c" "$limit" "$((limit/1024/1024))"
  fi
done

sub "Restart en OOM history"
for c in $API $PG ${LLM:-}; do
  [ -z "$c" ] && continue
  docker inspect "$c" --format '{{.Name}}: OOMKilled={{.State.OOMKilled}} RestartCount={{.RestartCount}} Status={{.State.Status}}'
done

sub "OOM events in dmesg (laatste week, indien toegankelijk)"
journalctl -k --since "7 days ago" 2>/dev/null | grep -iE "out of memory|oom-killer|killed process" | tail -10 \
  || echo "  (geen journalctl toegang of geen OOM events)"

# ---------- 2. Database connection druk ----------
section "2. Database connecties"

sub "Actieve connecties per state"
docker exec "$PG" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  SELECT count(*) AS aantal, state, application_name
  FROM pg_stat_activity
  WHERE datname = current_database()
  GROUP BY state, application_name
  ORDER BY aantal DESC;"' 2>&1

sub "max_connections setting"
docker exec "$PG" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SHOW max_connections;"' 2>&1

sub "Pool errors in api logs (laatste 7 dagen)"
docker logs "$API" --since 168h 2>&1 \
  | grep -iE "too many connections|QueuePool|connection refused|connection reset|TimeoutError: QueuePool" \
  | sort | uniq -c | sort -rn | head -20 \
  || echo "  (geen pool errors gevonden)"

# ---------- 3. Stale connectie symptomen ----------
section "3. Stale connection symptomen (laatste 7 dagen)"
docker logs "$API" --since 168h 2>&1 \
  | grep -iE "server closed the connection|broken pipe|connection invalidated|SSL connection has been closed|InterfaceError" \
  | sort | uniq -c | sort -rn | head -20
echo "  (leeg = goed; >0 hits/week rechtvaardigt pool_pre_ping)"

# ---------- 4. Dubbele LLM calls (kosten) ----------
section "4. Items met/zonder summary"
docker exec "$PG" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  SELECT
    count(*) FILTER (WHERE summary IS NOT NULL) AS met_summary,
    count(*) FILTER (WHERE summary IS NULL)     AS zonder_summary,
    count(*)                                    AS totaal
  FROM items;"' 2>&1

sub "Summarize aanroepen in api logs (laatste 7 dagen)"
total=$(docker logs "$API" --since 168h 2>&1 | grep -cE "_summarize_single_item|/summarize_item" || echo 0)
echo "  Totaal summarize aanroepen: $total"

# ---------- 5. LLM timeout hits ----------
section "5. LLM timeout / hang signalen (laatste 7 dagen)"
docker logs "$API" --since 168h 2>&1 \
  | grep -iE "ReadTimeout|httpx.*timeout|TimeoutException|asyncio.TimeoutError" \
  | sort | uniq -c | sort -rn | head -20
echo "  (leeg = 180s is genoeg; veel hits = timeout omhoog, niet omlaag)"

# ---------- 6. Algemene error sample ----------
section "6. Recente errors (laatste 24u, top 10)"
docker logs "$API" --since 24h 2>&1 \
  | grep -iE "ERROR|CRITICAL|Traceback" \
  | sort | uniq -c | sort -rn | head -10

# ---------- 7. Host RAM ----------
section "7. Host RAM"
free -h 2>/dev/null || vm_stat 2>/dev/null || echo "  (free/vm_stat niet beschikbaar)"

section "Klaar"
echo "Deel de output van dit script terug — daarmee bepalen we per Kimi-voorstel"
echo "of het echt nodig is of premature optimization."
