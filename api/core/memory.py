"""Mem-gate: workers weigeren nieuwe items te claimen als de werkelijk
beschikbare RAM onder een drempel zakt. Voorkomt OOM op kleine VPS waar
andere stacks (n8n, authentik, etc.) al een paar GB opeten.

Bron van "beschikbaar" staat in available_mem_mb(): prefer cgroup-v2
(memory.max - memory.current) zodat de gate correct werkt ook als de
container een memory-limit heeft. Valt terug op MemAvailable uit
/proc/meminfo voor cgroup-v1 of niet-container setups.

Drempels (settings): 50MB transcribe / 150MB summarize. stroom-api runt zelf
GEEN Whisper — dat zit in samenvat-agent (aparte container). De
transcribe-worker doet hier alleen een goedkope HTTP-dispatch (paar MB); de
1.6GB-piek valt elders. De transcribe-drempel hoort dus LAGER te zijn dan
summarize (dat wél in-proces LLM-werk doet), niet hoger.

Regressie (#59, 2026-06-24): transcribe stond op 200 > summarize 150. Op de
krappe 768MB cgroup hield de summarize-backlog het beschikbare geheugen tussen
150-200MB → summarize claimde wél, transcribe nooit → permanente uithongering
(structureel "0 transcripties" terwijl samenvattingen doorliepen). Door de
cheap dispatch ONDER de summarize-drempel te zetten krijgt transcribe weer
voorrang als RAM krap is; de single-GPU-constraint (max 1 'transcribing')
begrenst de echte capaciteit toch al.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional

log = logging.getLogger("stroom.memory")

MEM_GATE_LOG_EVERY_SEC = 300  # Throttle "wachten op geheugen"-logs naar 1x / 5min


def _cgroup_v2_available_mb() -> Optional[int]:
    """Beschikbare RAM binnen de cgroup-v2 memory-limit, in MB.

    Berekent (memory.max - memory.current) + reclaimable, waarbij
    reclaimable = inactive_file + slab_reclaimable uit memory.stat. Net als
    MemAvailable telt dit reclaimable page-cache mee als "beschikbaar": die
    cache groeit over de uptime tot tegen memory.max aan, maar de kernel
    claimt 'm terug vóór een OOM. Zonder die correctie zou (max - current)
    langzaam richting 0 zakken en de gate ten onrechte permanent blokkeren.

    Geeft None terug (→ proc-fallback) als:
      - cgroup-v2 niet beschikbaar is (bv. cgroup-v1 host)
      - memory.max op "max" staat (geen limit)
      - leesfout op max/current
    Een echte 0 (cgroup zit werkelijk vol) wordt als 0 teruggegeven, niet
    als None — zodat de gate dan blokkeert i.p.v. fail-open te gaan.
    """
    try:
        with open('/sys/fs/cgroup/memory.max') as f:
            max_str = f.read().strip()
        if max_str == 'max':
            return None  # Geen limit; proc-fallback is informatiever
        max_bytes = int(max_str)
        with open('/sys/fs/cgroup/memory.current') as f:
            cur_bytes = int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None

    # Reclaimable page-cache + slab telt mee als beschikbaar. Ontbreekt
    # memory.stat, dan reclaimable=0: conservatief (kan ten onrechte
    # blokkeren) maar nooit te optimistisch.
    reclaimable = 0
    try:
        with open('/sys/fs/cgroup/memory.stat') as f:
            for line in f:
                key, _, val = line.partition(' ')
                if key in ('inactive_file', 'slab_reclaimable'):
                    reclaimable += int(val)
    except (FileNotFoundError, ValueError, OSError):
        pass

    return max(0, (max_bytes - cur_bytes) + reclaimable) // (1024 * 1024)


def _proc_memavailable_mb() -> Optional[int]:
    """MemAvailable uit /proc/meminfo, in MB. None bij leesfout (gate uit)."""
    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return None


def available_mem_mb() -> Optional[int]:
    """Beschikbare RAM voor de mem-gate, in MB. None bij leesfout (gate uit)."""
    cgroup = _cgroup_v2_available_mb()
    if cgroup is not None:
        return cgroup
    return _proc_memavailable_mb()


# Per-worker state voor throttled mem-gate logging.
_LAST_MEM_GATE_LOG: Dict[str, float] = {}


def mem_gate_blocks(worker_name: str, min_mb: int) -> bool:
    """True als beschikbare RAM onder de drempel zit. Logt throttled."""
    avail = available_mem_mb()
    if avail is None:
        return False  # mem-stats onleesbaar — gate uit, fail open
    if avail >= min_mb:
        return False
    now = time.time()
    last = _LAST_MEM_GATE_LOG.get(worker_name, 0.0)
    if now - last >= MEM_GATE_LOG_EVERY_SEC:
        log.info("[%s] mem-gate: %dMB available, need %dMB — wachten",
                 worker_name, avail, min_mb)
        _LAST_MEM_GATE_LOG[worker_name] = now
    return True
