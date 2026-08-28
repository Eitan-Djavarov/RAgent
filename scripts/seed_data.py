#!/usr/bin/env python3
"""Seed Tech-Doc-Intelligence with aerospace/defense incident reports."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:5000"
CREATE_PATH = "/api/incidents"


@dataclass(frozen=True)
class SeedIncident:
    title: str
    description: str
    system_name: str
    severity: str
    subsystem_tags: list[str]


INCIDENTS: list[SeedIncident] = [
    SeedIncident(
        title="UAV C2 telemetry drop during contested RF jamming near waypoint WP-17",
        system_name="UAV-Link-X",
        severity="critical",
        subsystem_tags=["rf-link", "c2-telemetry", "anti-jam", "uav-airborne"],
        description=(
            "Root cause analysis indicates adaptive barrage jamming centered near 2.4 GHz with "
            "periodic swept tones that drove the UAV-Link-X modem into repeated Automatic Repeat "
            "reQuest (ARQ) stalls. The airborne radio reduced MCS under measured SINR collapse "
            "from +11 dB to -4 dB within 2.8 seconds after entering the contested corridor west of "
            "WP-17. Link-layer FEC remained enabled, but the ground data terminal's beam-steering "
            "loop lagged the air vehicle heading change by approximately 420 ms, producing "
            "deep fades and burst packet loss. Primary causal factors were (1) insufficient "
            "frequency-hop dwell randomization against the observed jammer sweep rate and "
            "(2) stale antenna pointing ephemeris after a delayed INS/GPS fusion update.\n\n"
            "Observed symptoms included intermittent loss of command-and-control heartbeats, "
            "frozen HUD telemetry panes, and automatic transition of the air vehicle into "
            "lost-link contingency orbit. Operators reported that video ISR remained partially "
            "available on the secondary Ku path while the L/S-band C2 channel dropped. "
            "Onboard BIT codes asserted LINK_DEGRADED and NAV_COAST_ACTIVE. Ground watch "
            "floor screens showed 'NO COMM' for 47 seconds with intermittent 1-3 second recoveries. "
            "Mission abort criteria were approached but not crossed because the contingency "
            "orbit held inside the approved airspace polygon.\n\n"
            "Telemetry excerpts (UTC): "
            "T+0.0s SINR=11.2dB RSSI=-61dBm MCS=9; "
            "T+1.4s SINR=3.1dB RSSI=-79dBm MCS=4 ARQ_retry=18; "
            "T+2.8s SINR=-4.0dB RSSI=-91dBm MCS=1 FER=0.62; "
            "T+8.1s hop_set_switch=TRUE; "
            "T+14.6s SINR=6.4dB partial_recover; "
            "T+47.0s C2_heartbeat restored. "
            "RF spectrum capture showed a 28 MHz wide noise pedestal + swept CW tone at ~180 Hz "
            "modulation. Aircraft attitude log confirmed a 22 deg bank coincident with the fade.\n\n"
            "Mitigation steps: (1) enable contested-spectrum hop profile PROFILE_AJ_B with shorter "
            "dwell and cryptographic hop-seed refresh; (2) tighten antenna pointing prediction "
            "using 50 Hz INS extrapolation during GPS coast; (3) raise lost-link timer from 30s "
            "to 60s only inside approved polygons; (4) pre-brief alternate C2 relay UAV; "
            "(5) patch modem firmware 4.12.3 to ignore jammer-like swept CW false AGC locks. "
            "Follow-up flight test required in anechoic + open-air EW range before next contested sortie."
        ),
    ),
    SeedIncident(
        title="Radar-APG track processor RSS growth and watchdog resets under dense target load",
        system_name="Radar-APG",
        severity="high",
        subsystem_tags=["signal-processor", "track-file", "memory", "radar-mode-tws"],
        description=(
            "Root cause was identified as a non-releasing allocation path in the track-file "
            "association worker when operating Track-While-Scan (TWS) with >180 simultaneous "
            "hypotheses. A circular buffer of association scratch tensors was appended on every "
            "dwell but only partially reclaimed when hypotheses were pruned, producing a steady "
            "resident set size (RSS) climb of ~9-12 MB/min. After approximately 41 minutes of "
            "continuous high-density maritime/air picture, the process approached the 6.5 GB "
            "cgroup limit, triggered jemalloc fragmentation warnings, and was restarted by the "
            "mission computer watchdog. Secondary contributor: debug trace ring intentionally left "
            "enabled in the field image captured additional per-target strings.\n\n"
            "Symptoms observed by operators: intermittent 'TRACK PROCESSOR DEGRADED' alerts, "
            "stale velocity vectors on the tactical display, and brief blanking of the PPI overlay "
            "during soft resets. No hard kill of the RF front-end occurred; receiver and "
            "waveform generator stayed online. During the event the system dropped from 214 "
            "firm tracks to 57, then recovered to 190 after restart. Maintainers noted elevated "
            "CPU steal on DSP board B and rising page faults.\n\n"
            "Telemetry / logs: "
            "rss_mb[t0]=1840, rss_mb[t20m]=2210, rss_mb[t40m]=6120; "
            "hypotheses_active=188; dwell_rate_hz=42; "
            "alloc_fail_count=0 until t=40m52s then alloc_fail_count=37; "
            "watchdog_reset_count=1; "
            "journal: 'track_assoc_worker: scratch arena high water 5.9GB'; "
            "'cgroup memory.max approaching'; 'process restart pid=44821'. "
            "Perf snapshot showed 38% time in Eigen::Matrix multiply and 12% in fmt::format "
            "inside debug tracing.\n\n"
            "Mitigation: hotfix build disables field debug ring; introduce RAII arena reset each "
            "dwell; add soft memory governor that forces hypothesis prune at 75% RSS; soak-test "
            "with 250 synthetic targets for 4 hours gate for release; add Grafana alert on "
            "rss_mb slope >8 MB/min sustained 5 minutes. Long-term redesign moves association "
            "scratch to a pre-sized pool owned by the waveform epoch."
        ),
    ),
    SeedIncident(
        title="Gimbal-EOIR line-of-sight jitter exceeding 180 urad in severe turbulence",
        system_name="Gimbal-EOIR",
        severity="high",
        subsystem_tags=["eo-ir", "gimbal", "stabilization", "imu-fusion"],
        description=(
            "Root cause analysis traced LOS instability to saturated rate-gyro feedback during "
            "high-frequency turbulence (vertical gust spectrum peaking near 7-9 Hz) combined with "
            "an overly aggressive notch filter that attenuated legitimate stabilization commands. "
            "The inner rate loop could not reject disturbance torques once the IMU RMS rate "
            "exceeded 18 deg/s. A contributing firmware defect delayed feed-forward from the "
            "aircraft INS by one 2.5 ms frame after mode switch into 'point-track', producing "
            "phase lag visible as 2-3 pixel blur on MWIR at 600 mm EFL.\n\n"
            "Observed symptoms: operators reported 'swimming' of the crosshair, auto-tracker "
            "coast events, and automatic FOV widen as the tracker confidence fell below 0.55. "
            "Still frames showed motion smear; laser spot-tracker SNR dropped 4.5 dB. No "
            "mechanical hard-stop collisions were recorded, but motor current peaks hit 92% of "
            "continuous rating on the elevation axis.\n\n"
            "Telemetry highlights: "
            "los_jitter_urad_rms=186 (limit=80); "
            "imu_rate_rms_dps=19.4; "
            "elev_motor_current_a_pk=6.1; "
            "tracker_conf_min=0.41; "
            "ins_feedforward_delay_frames=1; "
            "gust_load_factor=1.7. "
            "BIT remained GREEN for heaters and coolers. Vibration accelerometer on gimbal yoke "
            "measured 2.3 gRMS between 5-15 Hz.\n\n"
            "Mitigation steps: retune notch to spare 7-10 Hz band; enable adaptive gain scheduling "
            "keyed to IMU RMS; patch INS feed-forward timing; temporarily restrict auto-tracker "
            "to WFOV in turbulence severity >moderate; schedule damper inspection and balance "
            "check on elevation axis. Validate with 6DOF disturbance injection on the HWIL rig "
            "before next ISR detachment."
        ),
    ),
    SeedIncident(
        title="Mission computer thermal throttling during continuous SAR + ATR compute load",
        system_name="Mission-CMP-9",
        severity="medium",
        subsystem_tags=["mission-computer", "thermal", "gpu", "sar-atr"],
        description=(
            "Root cause: sustained synthetic aperture radar (SAR) formation flying combined with "
            "onboard automatic target recognition (ATR) CNN inference drove the Mission-CMP-9 "
            "GPU complex beyond the thermal design point in hot-day conditions (OAT 39 C at "
            "FL180). Cold-plate flow was within pump spec, but a partially clogged heat exchanger "
            "on the liquid loop reduced effective heat rejection by an estimated 18%. When GPU "
            "junction temperature crossed 92 C, the platform firmware engaged DVFS throttling, "
            "cutting clocks ~27% and extending ATR frame latency beyond the tactical budget.\n\n"
            "Symptoms: mission software posted THERMAL_THROTTLE_ACTIVE; SAR image tiles arrived "
            "with increasing latency; ATR confidence updates slowed from 8 Hz to ~3 Hz; operators "
            "saw yellow 'COMPUTE DEGRADED' banners. Navigation and weapons buses were unaffected. "
            "No spontaneous reboot occurred, but a thermal protective margin alarm latched.\n\n"
            "Telemetry: "
            "gpu_tj_c=94.8; cpu_pkg_c=81.2; coolant_in_c=41.0; coolant_out_c=49.6; "
            "pump_rpm=9200 (nominal); dp_hex_kpa=11.2 (expected 16-18); "
            "gpu_clock_mhz=1180 -> 860; atr_latency_ms=42 -> 118; "
            "sar_queue_depth=17. "
            "Maintenance review of HEX photos confirmed particulate fouling on the air-side fins "
            "after desert detachment.\n\n"
            "Mitigation: clean/replace HEX; raise inlet temp alarm to earlier advisory at 38 C "
            "coolant-in; implement mission mode that sheds ATR batch size under throttle; "
            "add predictive thermal model using OAT + SAR duty cycle; verify TIM pads on GPU "
            "cold plate at next phase inspection. Re-fly thermal profile with clean HEX before "
            "declaring full mission capable."
        ),
    ),
    SeedIncident(
        title="IFF Mode 5 Level 2 reply dropouts correlated with AESA sidelobe illumination",
        system_name="IFF-XPDR-M5",
        severity="high",
        subsystem_tags=["iff", "mode5", "emc", "transponder"],
        description=(
            "Root cause investigation linked intermittent Mode 5 Level 2 reply failures to "
            "electromagnetic coupling from AESA radar sidelobes during certain scan sectors. "
            "When the Radar-APG beam dwell aligned within 18 deg of the upper IFF blade antenna "
            "boresight, coupled energy compressed the transponder front-end LNA, elevating "
            "reply BER and causing cryptographic reply timeouts at the interrogator. Bench "
            "replications with a conducted injection of -8 dBm at 1090 MHz adjacent energy "
            "reproduced the dropout signature.\n\n"
            "Observed symptoms: intermittent 'FRIEND' to 'UNKNOWN' flips on the fused track "
            "picture, increased interrogator re-challenge rate, and crew reports of flickering "
            "IFF symbology on the SA display. No crypto key zeroization occurred. Built-in test "
            "remained intermittent FAIL only while the radar occupied the offending scan sector.\n\n"
            "Telemetry/logs: "
            "m5_reply_success_ratio=0.71 (req>=0.95); "
            "lna_compress_events=44/min peak; "
            "radar_sector_az=112-130 deg coincidence=0.89; "
            "xpdr_temp_c=61; "
            "crypto_channel_ok=TRUE. "
            "Spectrum probe at antenna feed showed transient energy peaks 12 dB above nominal "
            "noise floor synchronized with AESA pulse groups.\n\n"
            "Mitigation: install additional cavity filter / blanking gate synchronized to AESA "
            "emit windows; update EMC ICD to blank IFF listen during specific sidelobe geometry; "
            "temporary tactic—avoid simultaneous AESA high-power search in the 112-130 deg "
            "relative sector during dense IFF interrogation; schedule flight EMC retest after "
            "filter fit. Track as airworthiness EMC Category B until closed."
        ),
    ),
    SeedIncident(
        title="Flight-control actuator oscillatory coupling after FCS gain schedule update",
        system_name="FCS-ACT-7",
        severity="critical",
        subsystem_tags=["flight-controls", "actuator", "aeroservoelastic", "gain-schedule"],
        description=(
            "Root cause: a recently deployed FCS gain schedule increased roll-channel "
            "proportional gain by 12% above Mach 0.78 without updating the structural notch "
            "aligned to the wing first bending mode (~8.6 Hz). In combination with a slightly "
            "softened actuator hydraulic damping orifice (wear), the closed-loop system excited "
            "a lightly damped aeroservoelastic oscillation. Pilots perceived a buzz in the "
            "lateral stick and wing tip; safety pilot disconnected the autopilot and recovered.\n\n"
            "Symptoms: intermittent roll-axis oscillation between 8.4-8.8 Hz, elevated "
            "actuator rate commands, and automatic oscillation detection (AOD) caution. Loads "
            "telemetry remained below ultimate but exceeded fatigue monitoring thresholds for "
            "34 seconds. No hydraulic pressure loss. Maintenance found orifice diameter out of "
            "wear tolerance on the right aileron actuator.\n\n"
            "Telemetry: "
            "fcs_build=7.4.1-g12; mach=0.81; alt_ft=22100; "
            "ail_rate_cmd_dps_rms=14.2; accel_wingtip_g_pk=0.41; "
            "aod_trip=TRUE; hyd_press_psi=2950; "
            "notch_8p6_enable=FALSE (regressed). "
            "FFT of rate gyro confirmed a coherent 8.55 Hz line 11 dB above baseline.\n\n"
            "Mitigation: immediate rollback of gain schedule g12; ground replace right aileron "
            "actuator; reinstate 8.6 Hz notch with verification on iron bird; add CI gate that "
            "fails builds if aeroelastic notch flags regress; fleet inspection of orifice wear "
            "on sibling actuators. Clearance for flight only after iron-bird + first-flight "
            "instrumented envelope expansion."
        ),
    ),
    SeedIncident(
        title="Data-link encryption resync storms after ground crypto zeroize drill",
        system_name="UAV-Link-X",
        severity="medium",
        subsystem_tags=["crypto", "data-link", "key-management", "ground-segment"],
        description=(
            "Root cause: after a planned ground crypto zeroize/reload drill, the ground mission "
            "segment loaded a valid but epoch-mismatched black key package relative to the "
            "airborne store. The link repeatedly attempted secure association, failed MIC "
            "verification, tore down, and retried every 3 seconds, creating a resync storm that "
            "consumed C2 bandwidth and flooded operator alerts. Airborne keys were correct for "
            "the mission epoch; the ground loader script skipped the epoch-check step after a "
            "manual override used during the drill.\n\n"
            "Symptoms: continuous 'SECURE ASSOC FAIL' toasts, oscillating link state "
            "UP/DOWN, elevated CPU on the ground crypto module, and delayed non-secure "
            "telemetry because the modem control plane was busy. The air vehicle remained in "
            "a safe orbit under lost-secure-link rules with contingency plain-text beacon only.\n\n"
            "Telemetry: "
            "assoc_fail_count=128 over 6.4 min; "
            "mic_fail_reason=EPOCH_MISMATCH; "
            "ground_key_epoch=2026.214; air_key_epoch=2026.215; "
            "retry_period_s=3; cpu_crypto_pct=78. "
            "Audit log shows loader flag --skip-epoch-check=true set by drill operator.\n\n"
            "Mitigation: remove ability to skip epoch check in production loader profiles; "
            "add pre-flight cross-compare of air/ground key epochs in the mission checklist UI; "
            "rate-limit assoc retries with exponential backoff; retrain ops on post-drill "
            "verification. Incident closed after loading matching epoch 2026.215 and confirming "
            "stable secure link for 45 minutes."
        ),
    ),
    SeedIncident(
        title="SAR motion-compensation divergence from intermittent GPS/INS coast quality drop",
        system_name="Radar-APG",
        severity="medium",
        subsystem_tags=["sar", "motion-comp", "gps-ins", "image-quality"],
        description=(
            "Root cause: during a high-squint SAR collect, the embedded GPS receiver experienced "
            "intermittent carrier-phase dropouts due to airframe masking and mild ionospheric "
            "scintillation. The INS coast solution accumulated azimuth drift beyond the "
            "motion-compensation budget (0.02 deg), causing focus degradation and range-walk "
            "residuals. The SAR processor continued to accept NAV quality flag 'DEGRADED' "
            "instead of aborting to a lower-resolution fallback mode because the quality gate "
            "threshold was set too permissively in software load 5.9.2.\n\n"
            "Symptoms: formed imagery showed smeared strong scatterers, autofocus iterations "
            "hitting max count, and operator reports of 'soft' map overlays. No RF hardware "
            "faults. Parallel GMTI mode remained usable. Mission still collected data but "
            "exploitation confidence was reduced for fixed-target detection.\n\n"
            "Telemetry: "
            "gps_phase_lock_loss_events=11; ins_coast_s_max=18.4; "
            "nav_az_err_est_deg=0.051; sar_focus_metric=0.61 (target>=0.85); "
            "autofocus_iters=40 (max); quality_gate_pass=TRUE (bug). "
            "SPAN logs correlated dropouts with 25 deg banked turns masking the upper antenna.\n\n"
            "Mitigation: tighten NAV quality gate for high-squint SAR; auto-switch to DBS/low "
            "resolution when coast >8s; advise aircrew turn profiles that preserve GPS "
            "visibility during collect; evaluate dual-antenna GPS heading aid; patch 5.9.3 "
            "with gate fix and regression imagery tests on the SAR archive suite."
        ),
    ),
]


def build_payload(incident: SeedIncident) -> dict[str, Any]:
    return {
        "title": incident.title,
        "description": incident.description,
        "systemName": incident.system_name,
        "severity": incident.severity,
        "subsystemTags": incident.subsystem_tags,
    }


def seed(base_url: str, timeout_s: float, dry_run: bool) -> int:
    endpoint = base_url.rstrip("/") + CREATE_PATH
    print(f"Seeding {len(INCIDENTS)} aerospace/defense incidents -> {endpoint}")
    if dry_run:
        for index, incident in enumerate(INCIDENTS, start=1):
            print(f"[{index}/{len(INCIDENTS)}] DRY-RUN {incident.system_name}: {incident.title}")
        print("Dry run complete. No HTTP calls were made.")
        return 0

    created = 0
    failed = 0
    total_chunks = 0
    failures: list[str] = []

    with httpx.Client(timeout=timeout_s) as client:
        for index, incident in enumerate(INCIDENTS, start=1):
            payload = build_payload(incident)
            print(
                f"[{index}/{len(INCIDENTS)}] Creating {incident.system_name} "
                f"({incident.severity})..."
            )
            started = time.perf_counter()
            try:
                response = client.post(endpoint, json=payload)
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                if response.status_code >= 400:
                    failed += 1
                    detail = response.text.strip()
                    failures.append(
                        f"{incident.title} -> HTTP {response.status_code}: {detail[:300]}"
                    )
                    print(f"  ERROR HTTP {response.status_code} in {elapsed_ms:.0f} ms")
                    print(f"  Body: {detail[:400]}")
                    continue

                body = response.json()
                chunks = int(body.get("chunksIndexed") or body.get("chunksCount") or 0)
                incident_id = body.get("id", "unknown")
                indexed_at = body.get("indexedAt")
                total_chunks += chunks
                created += 1
                print(
                    f"  OK id={incident_id} chunksIndexed={chunks} "
                    f"indexedAt={indexed_at} ({elapsed_ms:.0f} ms)"
                )
            except httpx.TimeoutException as exc:
                failed += 1
                failures.append(f"{incident.title} -> timeout: {exc}")
                print(f"  ERROR timeout after {timeout_s:.0f}s: {exc}")
            except httpx.HTTPError as exc:
                failed += 1
                failures.append(f"{incident.title} -> transport: {exc}")
                print(f"  ERROR transport: {exc}")
            except json.JSONDecodeError as exc:
                failed += 1
                failures.append(f"{incident.title} -> invalid JSON: {exc}")
                print(f"  ERROR invalid JSON response: {exc}")

    print("\n======= Seed Summary =======")
    print(f"Target endpoint     : {endpoint}")
    print(f"Incidents attempted : {len(INCIDENTS)}")
    print(f"Created             : {created}")
    print(f"Failed              : {failed}")
    print(f"Total chunks indexed: {total_chunks}")
    if created:
        print(f"Avg chunks/incident : {total_chunks / created:.2f}")
    if failures:
        print("Failures:")
        for item in failures:
            print(f"  - {item}")
    print("============================")
    return 0 if failed == 0 else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed realistic aerospace/defense incidents into Tech-Doc-Intelligence.",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Backend base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180.0,
        help="Per-request timeout in seconds (default: 180)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print payloads that would be sent without calling the API",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return seed(base_url=args.base_url, timeout_s=args.timeout, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
