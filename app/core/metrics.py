from collections import Counter


_METRICS = Counter(
    {
        "webhook_received": 0,
        "event_processed": 0,
        "event_failed": 0,
        "event_reclaimed": 0,
        "event_dead_lettered": 0,
        "processing_latency_ms_sum": 0,
        "processing_latency_ms_count": 0,
    }
)



def inc(name: str, value: int = 1) -> None:
    _METRICS[name] += value


def observe_processing_latency(ms: int) -> None:
    _METRICS["processing_latency_ms_sum"] += ms
    _METRICS["processing_latency_ms_count"] += 1



def snapshot() -> dict[str, int]:
    values = dict(_METRICS)
    count = values.get("processing_latency_ms_count", 0)
    if count > 0:
        values["processing_latency_ms_avg"] = int(values["processing_latency_ms_sum"] / count)
    else:
        values["processing_latency_ms_avg"] = 0
    return values
