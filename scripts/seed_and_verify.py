#!/usr/bin/env python3
"""Seed defense/aerospace incidents and verify hybrid RAG ask endpoints."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

DEFAULT_BASE_URL = "http://localhost:5000"
HEALTH_PATH = "/api/health"
CREATE_PATH = "/api/incidents"
ASK_PATH = "/api/incidents/ask"


@dataclass(frozen=True)
class SeedIncident:
    title: str
    description: str
    system_name: str
    severity: str
    subsystem_tags: list[str]


@dataclass
class AskResult:
    query: str
    passed: bool
    latency_ms: float
    citation_count: int
    summary_preview: str
    detail: str


INCIDENTS: list[SeedIncident] = [
    SeedIncident(
        title="UAV SATCOM link degradation under electronic warfare jamming",
        system_name="Tactical-UAV-V2",
        severity="critical",
        subsystem_tags=["satcom", "ew", "uav", "c2-link"],
        description=(
            "Root cause investigation attributed the SATCOM degradation to a coordinated electronic "
            "warfare barrage that combined spot jamming on the uplink guard band with swept "
            "noise across the Ku-band return channel used by Tactical-UAV-V2 modem firmware "
            "build 6.4.11-AJ. The airborne terminal's automatic gain control locked onto the "
            "jammer pedestal, collapsing measured Es/N0 from 9.8 dB to -1.2 dB within four "
            "seconds after the vehicle entered grid square 18S. A secondary causal factor was "
            "stale ephemeris for the geostationary relay, which delayed beam steering by roughly "
            "380 milliseconds during a banked turn and amplified deep fades. Cryptographic "
            "association remained intact, but ARQ retries saturated the control plane and "
            "starved telemetry frames. Observed symptoms included intermittent loss of C2 "
            "heartbeats, frozen map overlays on the ground control station, BIT codes "
            "LINK_DEGRADED and SATCOM_AGC_SAT, and automatic transition into lost-link "
            "contingency orbit after twenty-nine seconds without a valid uplink. Operators "
            "reported that EO/IR video on the secondary S-band path continued at reduced "
            "bitrate while the primary SATCOM pipe dropped. Telemetry excerpts (UTC): "
            "T+0.0s EsN0=9.8dB RSSI=-67dBm MCS=8; T+1.6s EsN0=3.1dB ARQ_retry=22; "
            "T+4.0s EsN0=-1.2dB FER=0.71; T+9.5s hop_profile=AJ_CHARLIE; T+29.0s "
            "lost_link_orbit=TRUE. Spectrum captures showed a 36 MHz noise pedestal with a "
            "1.1 kHz swept CW tone coincident with the fade. Mitigation steps executed in the "
            "field were: enable contested hop profile AJ_CHARLIE with shortened dwell, force "
            "INS-aided antenna prediction at 50 Hz during GPS coast, raise lost-link timer to "
            "sixty seconds inside approved polygons only, pre-position a relay UAV on the "
            "alternate Ka path, and patch modem firmware to 6.4.12 to reject jammer-like AGC "
            "locks. Post-event soak in the anechoic EW chamber confirmed recovery with Es/N0 "
            "above 7 dB under the same barrage profile. Follow-on actions include updating the "
            "mission EW playbook and requiring AJ_CHARLIE as default for contested corridors."
        ),
    ),
    SeedIncident(
        title="AESA Radar signal processor buffer overflow during multi-target tracking",
        system_name="Radar-AESA-90",
        severity="high",
        subsystem_tags=["aesa", "signal-processor", "track-file", "memory"],
        description=(
            "Root cause analysis identified a heap buffer overflow inside the track-association "
            "worker of Radar-AESA-90 signal processor software load SP-5.9.2 when Track-While-Scan "
            "maintained more than one hundred ninety simultaneous hypotheses. The association "
            "scratch arena appended per-dwell tensors without reclaiming pruned hypothesis slots, "
            "so resident set size climbed approximately eleven megabytes per minute. After "
            "forty-three minutes of dense maritime and air picture, the process approached the "
            "6.5 GB cgroup ceiling, jemalloc reported fragmentation warnings, and the mission "
            "computer watchdog soft-reset the DSP partition. A contributing defect left the "
            "field debug ring enabled, which serialized per-target strings into the same arena. "
            "Observed symptoms were intermittent TRACK_PROCESSOR_DEGRADED alerts, stale velocity "
            "vectors on the tactical display, brief PPI blanking during soft reset, and a drop "
            "from two hundred fourteen firm tracks to fifty-nine before recovery to one hundred "
            "ninety-two. RF front-end and waveform generator remained online. Telemetry and "
            "journal excerpts: rss_mb[t0]=1760; rss_mb[t20m]=2285; rss_mb[t43m]=6480; "
            "hypotheses_active=194; dwell_rate_hz=44; alloc_fail_count=41 near trip; "
            "watchdog_reset_count=1; log line 'track_assoc_worker: scratch arena high water "
            "6.1GB' followed by 'cgroup memory.max approaching'. Perf samples showed thirty-nine "
            "percent time in matrix multiply kernels and fourteen percent in debug formatting. "
            "Mitigation included an emergency hotfix disabling the field debug ring, introducing "
            "RAII arena reset each dwell, adding a soft memory governor that prunes hypotheses "
            "at seventy-five percent RSS, and gating release on a four-hour soak with two "
            "hundred fifty synthetic targets. Grafana alerts now fire when rss_mb slope exceeds "
            "eight megabytes per minute for five consecutive minutes. Long-term redesign moves "
            "association scratch into a pre-sized pool owned by the waveform epoch. Validation "
            "on the HWIL radar stimulator confirmed stable RSS below 2.4 GB for six hours after "
            "the hotfix."
        ),
    ),
    SeedIncident(
        title="EO/IR stabilized gimbal angular drift during supersonic thermal transition",
        system_name="EOIR-Pod-X",
        severity="medium",
        subsystem_tags=["eo-ir", "gimbal", "thermal", "stabilization"],
        description=(
            "Root cause for the EOIR-Pod-X incident was angular drift of the stabilized line of "
            "sight during a rapid thermal transition while the host aircraft accelerated through "
            "Mach 1.1. Differential expansion between the aluminum yoke and titanium elevation "
            "shaft shifted the optical boresight by approximately two hundred ten microradians, "
            "exceeding the eighty microradian RMS specification. Firmware build GIM-3.2.7 applied "
            "an overly aggressive notch near seven to nine hertz that attenuated legitimate "
            "stabilization torque commands precisely when IMU rate RMS exceeded eighteen degrees "
            "per second in light turbulence coincident with the thermal soak. A one-frame "
            "delay in INS feed-forward after mode switch to point-track added phase lag visible "
            "as two-to-three pixel blur on MWIR at six hundred millimeter effective focal length. "
            "Observed symptoms included swimming crosshairs, auto-tracker coast events, automatic "
            "FOV widen when tracker confidence fell below 0.55, laser spot-tracker SNR drop of "
            "4.6 dB, and elevation motor current peaks at ninety-two percent of continuous rating. "
            "No hard-stop collisions occurred. Telemetry highlights: los_jitter_urad_rms=210; "
            "imu_rate_rms_dps=19.1; elev_motor_current_a_pk=6.0; tracker_conf_min=0.43; "
            "ins_feedforward_delay_frames=1; skin_temp_delta_c=38 over ninety seconds; "
            "gimbal_fw=GIM-3.2.7. Mitigation steps that restored performance were: retune the "
            "notch to spare the seven-to-ten hertz band, enable adaptive gain scheduling keyed "
            "to IMU RMS and skin-temperature rate, patch INS feed-forward timing in GIM-3.2.8, "
            "restrict auto-tracker to wide FOV during thermal-transition envelopes, and schedule "
            "damper inspection plus elevation-axis balance check. HWIL disturbance injection with "
            "thermal soak profiles confirmed los_jitter_urad_rms returned to sixty-seven after "
            "the firmware update. Operators were briefed to delay fine-track commits until skin "
            "temperature rate falls below two degrees Celsius per ten seconds."
        ),
    ),
    SeedIncident(
        title="Mission Computer FPGA bus arbitration timeout under sensor burst rate",
        system_name="Mission-Compute-Box",
        severity="critical",
        subsystem_tags=["fpga", "mission-computer", "bus-arbitration", "sensor-fusion"],
        description=(
            "Root cause analysis on Mission-Compute-Box traced critical FPGA bus arbitration "
            "timeouts to a priority inversion on the AXI interconnect when SAR, ESM, and EO "
            "sensor burst DMA overlapped at peak rate. Fabric bitstream MCB-FPGA-4.1.0 granted "
            "equal round-robin slices to three high-bandwidth masters without a starvation "
            "watchdog, so the flight-critical avionics master waited beyond the two hundred "
            "microsecond budget during a simultaneous SAR stripmap tile dump and ESM pulse "
            "descriptor flood. Soft ECC scrubbing on the same fabric increased contention by "
            "stealing cycles during combat mode, which had not been profiled against the new "
            "sensor burst envelopes introduced in the latest software drop. Observed symptoms "
            "included SENSOR_FUSION_STALL alerts, delayed weapon-bus heartbeats by up to "
            "eighteen milliseconds, intermittent NAV solution freezes lasting one to three "
            "frames, and automatic shedding of non-critical SAR formation to protect flight "
            "controls. Crew displays showed yellow COMPUTE_PATH_DEGRADED banners while "
            "weapons release inhibit remained false. No spontaneous reboot occurred, but the "
            "protective margin alarm latched and required maintenance acknowledge. Telemetry: "
            "axi_timeout_count=67 over four minutes; sar_burst_MBps=920; esm_pdw_rate_khz=180; "
            "avionics_wait_us_p99=260; bitstream=MCB-FPGA-4.1.0; cpu_load_pct=71; "
            "fabric_temp_c=79. Logic analyzer captures confirmed back-to-back SAR beats "
            "blocking the avionics port for stretches of two hundred forty microseconds. "
            "Mitigation deployed in the field: load bitstream MCB-FPGA-4.1.3 with weighted "
            "priority and a one hundred twenty microsecond preemption timer for the avionics "
            "master, cap SAR DMA bursts to 640 MB/s when ESM PDW rate exceeds 150 kHz, disable "
            "background ECC scrub during combat modes, and add a mission software governor that "
            "queues SAR tiles when axi_timeout_count rises. Iron-bird regression with worst-case "
            "sensor scripts showed avionics_wait_us_p99 reduced to ninety-four microseconds. "
            "Additional actions include CI gates that fail bitstreams lacking preemption timers "
            "and a fleet bulletin requiring 4.1.3 before next contested sortie."
        ),
    ),
    SeedIncident(
        title="Flight Control System (FCS) IMU sensor cross-check divergence error",
        system_name="Avionics-FCS",
        severity="high",
        subsystem_tags=["fcs", "imu", "cross-check", "avionics"],
        description=(
            "Root cause for the Avionics-FCS incident was a cross-check divergence between the "
            "primary and secondary IMU lanes after a cold-soak start at minus thirty-five Celsius "
            "followed by rapid climb. IMU lane B exhibited a bias ramp of 0.12 degrees per second "
            "squared on the roll axis due to incomplete temperature compensation tables in sensor "
            "firmware IMU-2.8.4, while lane A remained within specification. The FCS cross-monitor "
            "in software load FCS-7.5.1 declared DIV_IMU_CROSSCHECK when the lanes disagreed beyond "
            "0.05 degrees per second for more than two hundred milliseconds, forcing a transition "
            "to single-lane degraded mode with reduced control law authority. A wiring harness "
            "micro-fracture on the lane B power return contributed intermittent millivolt offsets "
            "that the BIT classified as soft failures only and therefore did not inhibit dispatch. "
            "Observed symptoms included amber FCS DEGRADED cues, brief autopilot disconnect "
            "prompts, elevated control surface activity during the divergence window, and crew "
            "reports of a subtle lateral bobble that settled after the monitor selected lane A. "
            "Loads remained below structural limits and no nuisance stick shaker events occurred. "
            "Telemetry: imu_b_roll_bias_dps2=0.12; crosscheck_residual_dps=0.07; div_timer_ms=240; "
            "fcs_mode=DEGRADED_SINGLE; imu_fw=IMU-2.8.4; fcs_sw=FCS-7.5.1; oat_c=-35 at start; "
            "alt_ft_transition=12000. Maintenance later confirmed the harness fretting under "
            "vibration survey. Mitigation steps: replace lane B IMU and inspect power-return "
            "harness, update IMU firmware to 2.8.6 with extended thermal compensation, raise "
            "cross-check debounce to three hundred milliseconds only for cold start envelopes, "
            "and add a preflight thermal soak BIT that rejects units with bias ramps above 0.05 "
            "degrees per second squared. Iron-bird cold-start campaigns confirmed no DIV trips "
            "across twenty cycles after the update. Flight clearance requires both firmware "
            "2.8.6 and harness inspection stamp before next instrumented envelope expansion."
        ),
    ),
    SeedIncident(
        title="Tactical C2 encrypted datalink packet loss over degraded VHF bandwidth",
        system_name="Comm-Tactical-Radio",
        severity="medium",
        subsystem_tags=["c2", "vhf", "encryption", "datalink"],
        description=(
            "Root cause analysis for Comm-Tactical-Radio packet loss pointed to congestion collapse "
            "on a degraded VHF tactical net when encrypted C2 traffic shared a twelve kilobit "
            "channel with voice relays during mountain multipath. Radio software COM-VHF-9.3.2 "
            "kept AES-GCM frame size fixed at large MTUs optimized for clear-sky twenty-four "
            "kilobit links, producing fragmentation and MIC failures as effective throughput fell "
            "to roughly seven kilobits per second. A ground relay incorrectly advertised higher "
            "bandwidth via stale OLSR metrics, so airborne nodes did not downshift and continued "
            "to push bulk track dumps into an already saturated pipe. Observed symptoms were "
            "oscillating SECURE_ASSOC state, operator toasts for MIC_FAIL, delayed blue-force "
            "updates by eight to fifteen seconds, and elevated CPU on the crypto module as rekey "
            "and retransmit storms overlapped. Voice remained intelligible but data queues grew "
            "without bound until the mission application shed non-critical tracks. Watch officers "
            "also noted repeated secure association flaps every three to four seconds aligned "
            "with multipath nulls. Telemetry: vhf_tput_kbps=7.1; mic_fail_count=96 over five "
            "minutes; retransmit_ratio=0.41; advertised_bw_kbps=24; com_fw=COM-VHF-9.3.2; "
            "crypto_cpu_pct=74; rssi_dbm=-98 with multipath notches. Spectrum monitoring "
            "confirmed deep fades every three to four seconds along the valley route. "
            "Mitigation: deploy COM-VHF-9.3.5 with adaptive MTU and early MIC fail backoff, "
            "force bandwidth probes every thirty seconds instead of trusting OLSR alone, "
            "prioritize encrypted heartbeats over bulk track dumps, and brief crews to enable "
            "mountain-profile preset before ingress. Field replay with recorded multipath "
            "traces showed retransmit_ratio reduced to 0.11 and blue-force latency under three "
            "seconds. Remaining work includes a network management rule that blocks stale "
            "bandwidth advertisements above measured probe capacity by more than twenty percent."
        ),
    ),
]


VERIFICATION_QUERIES: list[tuple[str, list[str]]] = [
    (
        "What caused the buffer overflow in the AESA radar during target tracking?",
        ["buffer", "aesa", "radar", "track", "overflow", "hypothesis", "rss", "scratch"],
    ),
    (
        "How was the EO/IR gimbal drift mitigated during thermal transition?",
        ["gimbal", "eo", "ir", "thermal", "mitigation", "notch", "feed-forward", "drift"],
    ),
    (
        "What were the symptoms of the UAV SATCOM link loss during EW jamming?",
        ["satcom", "uav", "jam", "ew", "heartbeat", "link", "agc", "esn0", "symptom"],
    ),
]


def word_count(text: str) -> int:
    return len([token for token in text.replace("\n", " ").split(" ") if token.strip()])


def validate_seed_corpus() -> None:
    for incident in INCIDENTS:
        count = word_count(incident.description)
        if count < 250 or count > 350:
            raise RuntimeError(
                f"Description for '{incident.title}' has {count} words; expected 250-350."
            )


def _request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout_s: float,
) -> tuple[int, dict[str, Any] | list[Any] | str]:
    if httpx is None:
        raise RuntimeError("httpx is required. Install with: pip install httpx")

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.request(method, url, json=payload)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"Timeout calling {method} {url}: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"HTTP transport error calling {method} {url}: {exc}") from exc

    body: dict[str, Any] | list[Any] | str
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = response.text

    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed with HTTP {response.status_code}: {body}")

    return response.status_code, body


def verify_health(base_url: str, timeout_s: float) -> None:
    url = base_url.rstrip("/") + HEALTH_PATH
    print(f"[A] Health check -> {url}")
    _, body = _request_json("GET", url, timeout_s=timeout_s)
    if not isinstance(body, dict):
        raise RuntimeError(f"Unexpected health payload type: {type(body)}")
    status = str(body.get("status", ""))
    service = str(body.get("service", ""))
    if not status:
        raise RuntimeError(f"Health payload missing status: {body}")
    print(f"    OK status={status} service={service}")


def ingest_incidents(
    base_url: str,
    timeout_s: float,
) -> list[dict[str, Any]]:
    url = base_url.rstrip("/") + CREATE_PATH
    print(f"[B] Ingesting {len(INCIDENTS)} incidents -> {url}")
    created: list[dict[str, Any]] = []
    for index, incident in enumerate(INCIDENTS, start=1):
        payload = {
            "title": incident.title,
            "description": incident.description,
            "systemName": incident.system_name,
            "severity": incident.severity,
            "subsystemTags": incident.subsystem_tags,
        }
        print(f"    [{index}/{len(INCIDENTS)}] {incident.system_name} ({incident.severity})...")
        started = time.perf_counter()
        _, body = _request_json("POST", url, payload=payload, timeout_s=timeout_s)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not isinstance(body, dict):
            raise RuntimeError(f"Unexpected create payload: {body}")
        incident_id = str(body.get("id", ""))
        chunks = int(body.get("chunksIndexed") or 0)
        if not incident_id:
            raise RuntimeError(f"Create response missing id: {body}")
        created.append(body)
        print(
            f"        OK id={incident_id} chunksIndexed={chunks} "
            f"({elapsed_ms:.0f} ms)"
        )
    return created


def _extract_answer_text(body: dict[str, Any]) -> str:
    parts = [
        str(body.get("summary") or ""),
        str(body.get("rootCause") or ""),
        str(body.get("actionItems") or ""),
        str(body.get("answer") or ""),
    ]
    return "\n".join(part for part in parts if part.strip())


def _latency_ms(body: dict[str, Any]) -> float:
    for key in ("latencyMs", "executionTimeMs", "LatencyMs"):
        value = body.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return -1.0


def _citations(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw = body.get("citations") or body.get("sources") or []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def run_verification_queries(
    base_url: str,
    timeout_s: float,
    seeded_ids: set[str],
) -> list[AskResult]:
    url = base_url.rstrip("/") + ASK_PATH
    print(f"[C] Running {len(VERIFICATION_QUERIES)} ask queries -> {url}")
    results: list[AskResult] = []

    for index, (query, keywords) in enumerate(VERIFICATION_QUERIES, start=1):
        payload = {"queryText": query, "topK": 4}
        print(f"    [{index}/{len(VERIFICATION_QUERIES)}] {query}")
        try:
            _, body = _request_json("POST", url, payload=payload, timeout_s=timeout_s)
            if not isinstance(body, dict):
                raise RuntimeError(f"Unexpected ask payload: {body}")

            answer_text = _extract_answer_text(body)
            latency = _latency_ms(body)
            citations = _citations(body)
            citation_blob = " ".join(
                f"{c.get('documentId', '')} {c.get('chunkText', '')}" for c in citations
            ).lower()
            answer_l = answer_text.lower()

            has_answer = len(answer_text.strip()) >= 40
            has_latency = latency >= 0
            has_citations = len(citations) > 0
            keyword_hit = any(keyword in answer_l or keyword in citation_blob for keyword in keywords)
            citation_id_hit = any(
                str(c.get("documentId", "")) in seeded_ids for c in citations
            ) or any(keyword in citation_blob for keyword in keywords)

            passed = has_answer and has_latency and has_citations and (keyword_hit or citation_id_hit)
            detail_parts = []
            if not has_answer:
                detail_parts.append("missing/short answer")
            if not has_latency:
                detail_parts.append("missing latency")
            if not has_citations:
                detail_parts.append("missing citations")
            if not (keyword_hit or citation_id_hit):
                detail_parts.append("citations/answer lack expected domain keywords")

            results.append(
                AskResult(
                    query=query,
                    passed=passed,
                    latency_ms=latency,
                    citation_count=len(citations),
                    summary_preview=(body.get("summary") or answer_text)[:80].replace("\n", " "),
                    detail="OK" if passed else "; ".join(detail_parts),
                )
            )
            print(
                f"        {'PASS' if passed else 'FAIL'} latencyMs={latency:.1f} "
                f"citations={len(citations)}"
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                AskResult(
                    query=query,
                    passed=False,
                    latency_ms=-1,
                    citation_count=0,
                    summary_preview="",
                    detail=str(exc),
                )
            )
            print(f"        FAIL error={exc}")

    print("[D] Assertions complete")
    return results


def print_ascii_table(results: list[AskResult]) -> None:
    headers = ("#", "RESULT", "LATENCY_MS", "CITATIONS", "QUERY")
    rows: list[tuple[str, str, str, str, str]] = []
    for index, item in enumerate(results, start=1):
        latency = f"{item.latency_ms:.1f}" if item.latency_ms >= 0 else "n/a"
        query = item.query if len(item.query) <= 64 else item.query[:61] + "..."
        rows.append(
            (
                str(index),
                "PASS" if item.passed else "FAIL",
                latency,
                str(item.citation_count),
                query,
            )
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        return "| " + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) + " |"

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    print()
    print(sep)
    print(fmt(headers))
    print(sep)
    for row in rows:
        print(fmt(row))
    print(sep)

    passed = sum(1 for item in results if item.passed)
    latencies = [item.latency_ms for item in results if item.latency_ms >= 0]
    avg = sum(latencies) / len(latencies) if latencies else 0.0
    print(f"Passed {passed}/{len(results)} | avg latency {avg:.1f} ms")
    for item in results:
        if not item.passed:
            print(f"  FAIL detail: {item.detail}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed six aerospace incidents and verify /api/incidents/ask responses.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Backend base URL")
    parser.add_argument("--timeout", type=float, default=180.0, help="HTTP timeout seconds")
    parser.add_argument(
        "--skip-validate-corpus",
        action="store_true",
        help="Skip local 250-350 word-count validation before calling the API",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if not args.skip_validate_corpus:
        validate_seed_corpus()
        print("Corpus validation OK (all descriptions are 250-350 words).")

    try:
        verify_health(args.base_url, args.timeout)
        created = ingest_incidents(args.base_url, args.timeout)
        seeded_ids = {str(item.get("id", "")) for item in created}
        results = run_verification_queries(args.base_url, args.timeout, seeded_ids)
    except Exception as exc:  # noqa: BLE001
        print(f"\nFATAL: {exc}", file=sys.stderr)
        return 2

    print_ascii_table(results)
    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
