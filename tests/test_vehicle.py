from __future__ import annotations

from safeloop_gameplay_qa.vehicle import build_vehicle_suite


def test_vehicle_suite_without_profile_is_uncalibrated():
    suite = build_vehicle_suite("Car", "gas", "brake", "left")
    assert suite["calibrated"] is False
    assert len(suite["scenarios"]) == 3
    assert all(not s["assertions"] for s in suite["scenarios"])


def test_vehicle_suite_maps_profile_to_machine_assertions():
    suite = build_vehicle_suite(
        "Car", "gas", "brake", "left",
        {"zero_to_100_s": {"min": 5, "max": 7}, "max_abs_roll_deg": {"max": 8}, "brake_distance_m": {"max": 42}},
    )
    assert suite["calibrated"] is True
    metrics = {a["metric"] for scenario in suite["scenarios"] for a in scenario["assertions"]}
    assert "zero_to_100_s" in metrics
    assert "brake_distance_m" in metrics
    assert "max_abs_roll_deg" in metrics
