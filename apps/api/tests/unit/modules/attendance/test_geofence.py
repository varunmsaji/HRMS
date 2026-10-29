"""Geofence decision rules (`hrms.modules.attendance.geofence`) — pure, no database."""

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from hrms.modules.attendance.geofence import (
    EARTH_RADIUS_M,
    FUTURE_SKEW_SECONDS,
    INSIDE,
    LOCATION_INVALID,
    LOCATION_REQUIRED,
    LOCATION_STALE,
    LOCATION_TOO_INACCURATE,
    LOCATION_UNAVAILABLE_CLIENT,
    NO_APPLICABLE_WORKPLACE,
    NOT_PROVIDED,
    OUTSIDE_GEOFENCE,
    OUTSIDE_GEOFENCE_UNCERTAIN,
    GeofencePolicy,
    ReportedLocation,
    Workplace,
    decide,
    haversine_m,
    nearest_workplace,
    round_coordinate,
    validate_location,
)

NOW = datetime(2026, 10, 28, 9, 0, 0, tzinfo=UTC)
KOCHI = (9.9312, 76.2673)
B1 = UUID("00000000-0000-0000-0000-000000000001")
B2 = UUID("00000000-0000-0000-0000-000000000002")

REQUIRED = GeofencePolicy(mode="REQUIRED", max_accuracy_m=50, max_age_seconds=60)
OPTIONAL = GeofencePolicy(mode="OPTIONAL", max_accuracy_m=50, max_age_seconds=60)
DISABLED = GeofencePolicy(mode="DISABLED", max_accuracy_m=50, max_age_seconds=60)


def north_of(point: tuple[float, float], metres: float) -> tuple[float, float]:
    """A point exactly `metres` due north (great-circle distance equals R * dphi on a meridian)."""
    return point[0] + math.degrees(metres / EARTH_RADIUS_M), point[1]


def office(radius: float = 100, branch: UUID = B1, at: tuple[float, float] = KOCHI) -> Workplace:
    return Workplace(
        branch_id=branch, name="Kochi", latitude=at[0], longitude=at[1], radius_m=radius
    )


def loc(
    at: tuple[float, float] = KOCHI, accuracy: float = 10, age: float = 5.0
) -> ReportedLocation:
    return ReportedLocation(
        latitude=at[0],
        longitude=at[1],
        accuracy_m=accuracy,
        captured_at=NOW - timedelta(seconds=age),
    )


def run(policy=REQUIRED, location=None, client_error=None, workplaces=None):
    return decide(
        policy=policy,
        location=location,
        client_error=client_error,
        workplaces=[office()] if workplaces is None else workplaces,
        now=NOW,
    )


# --- distance -------------------------------------------------------------------------------


def test_haversine_zero_for_same_point() -> None:
    assert haversine_m(*KOCHI, *KOCHI) == 0


def test_haversine_one_degree_of_latitude_is_about_111km() -> None:
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)


def test_haversine_known_city_pair() -> None:
    # Kochi -> Bengaluru: dlat 3.04deg (338 km), dlon 1.33deg*cos(11.5deg) (145 km) -> ~368 km.
    assert haversine_m(9.9312, 76.2673, 12.9716, 77.5946) == pytest.approx(368_000, rel=0.01)


def test_haversine_is_symmetric_and_handles_antimeridian() -> None:
    assert haversine_m(0, 179.9999, 0, -179.9999) == pytest.approx(
        haversine_m(0, -179.9999, 0, 179.9999)
    )
    assert haversine_m(0, 179.9999, 0, -179.9999) < 30


def test_haversine_at_poles_does_not_raise() -> None:
    assert haversine_m(90, 0, -90, 0) == pytest.approx(math.pi * EARTH_RADIUS_M, rel=1e-9)


# --- boundary -------------------------------------------------------------------------------


def test_exactly_on_the_radius_is_inside() -> None:
    assert run(location=loc(north_of(KOCHI, 100.0))).outcome == INSIDE


def test_just_inside_and_just_outside_the_radius() -> None:
    assert run(location=loc(north_of(KOCHI, 99.9))).outcome == INSIDE
    outside = run(location=loc(north_of(KOCHI, 100.5), accuracy=0))
    assert outside.outcome == OUTSIDE_GEOFENCE
    assert outside.allowed is False


def test_centre_is_inside_and_reports_zero_distance() -> None:
    decision = run(location=loc())
    assert decision.outcome == INSIDE and decision.distance_m == 0 and decision.allowed


def test_far_away_is_plainly_outside() -> None:
    decision = run(location=loc(north_of(KOCHI, 5000)))
    assert decision.outcome == OUTSIDE_GEOFENCE
    assert decision.distance_m == pytest.approx(5000, abs=1)
    assert decision.radius_m == 100


def test_outside_but_within_error_circle_is_uncertain_and_still_refused() -> None:
    # 110 m away, 30 m accuracy: the true position could be inside, but the radius is not widened.
    decision = run(location=loc(north_of(KOCHI, 110), accuracy=30))
    assert decision.outcome == OUTSIDE_GEOFENCE_UNCERTAIN
    assert decision.allowed is False


def test_outside_beyond_error_circle_is_plain_outside() -> None:
    assert run(location=loc(north_of(KOCHI, 200), accuracy=30)).outcome == OUTSIDE_GEOFENCE


def test_inside_with_acceptable_accuracy_is_accepted_even_if_error_circle_crosses_the_edge() -> (
    None
):
    # Documented: the reported point decides, bounded by the policy's accuracy ceiling.
    assert run(location=loc(north_of(KOCHI, 95), accuracy=40)).outcome == INSIDE


# --- accuracy / staleness / validity --------------------------------------------------------


def test_accuracy_exactly_at_limit_passes_and_above_fails() -> None:
    assert run(location=loc(accuracy=50)).outcome == INSIDE
    assert run(location=loc(accuracy=50.01)).outcome == LOCATION_TOO_INACCURATE


def test_age_exactly_at_limit_passes_and_above_fails() -> None:
    assert run(location=loc(age=60)).outcome == INSIDE
    assert run(location=loc(age=60.5)).outcome == LOCATION_STALE


def test_future_timestamp_within_skew_is_ok_beyond_is_invalid() -> None:
    assert run(location=loc(age=-(FUTURE_SKEW_SECONDS - 1))).outcome == INSIDE
    assert run(location=loc(age=-(FUTURE_SKEW_SECONDS + 5))).outcome == LOCATION_INVALID


def test_thresholds_come_from_policy_not_location() -> None:
    strict = GeofencePolicy(mode="REQUIRED", max_accuracy_m=5, max_age_seconds=5)
    assert run(policy=strict, location=loc(accuracy=10)).outcome == LOCATION_TOO_INACCURATE
    assert run(policy=strict, location=loc(age=10)).outcome == LOCATION_STALE


@pytest.mark.parametrize(
    ("lat", "lon", "acc"),
    [
        (91, 0, 5),
        (-91, 0, 5),
        (0, 181, 5),
        (0, -181, 5),
        (float("nan"), 0, 5),
        (0, float("inf"), 5),
        (0, 0, float("nan")),
        (0, 0, -1),
    ],
)
def test_invalid_numbers_are_rejected(lat: float, lon: float, acc: float) -> None:
    bad = ReportedLocation(lat, lon, acc, NOW)
    assert validate_location(bad) is False
    assert run(location=bad).outcome == LOCATION_INVALID


def test_naive_timestamp_is_invalid() -> None:
    naive = ReportedLocation(*KOCHI, 5, datetime(2026, 10, 28, 9, 0, 0))
    assert run(location=naive).outcome == LOCATION_INVALID


def test_timestamp_in_another_zone_is_compared_as_an_instant() -> None:
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    aware = ReportedLocation(*KOCHI, 5, (NOW - timedelta(seconds=5)).astimezone(ist))
    assert run(location=aware).outcome == INSIDE


# --- workplaces -----------------------------------------------------------------------------


def test_no_workplace_is_a_distinct_rejection() -> None:
    decision = run(location=loc(), workplaces=[])
    assert decision.outcome == NO_APPLICABLE_WORKPLACE and decision.allowed is False


def test_multiple_workplaces_nearest_by_margin_wins() -> None:
    far_site = north_of(KOCHI, 10_000)
    sites = [office(100, B1, KOCHI), office(100, B2, far_site)]
    decision = run(location=loc(north_of(far_site, 20)), workplaces=sites)
    assert decision.outcome == INSIDE and decision.branch_id == B2


def test_a_larger_fence_beats_a_closer_centre_when_margin_is_better() -> None:
    near_small = office(10, B1, KOCHI)
    farther_big = office(500, B2, north_of(KOCHI, 300))
    result = nearest_workplace(*north_of(KOCHI, 50), [near_small, farther_big])
    assert result is not None and result[0].branch_id == B2


def test_ties_break_on_branch_id_regardless_of_input_order() -> None:
    a, b = office(100, B1), office(100, B2)
    first = nearest_workplace(*KOCHI, [a, b])
    second = nearest_workplace(*KOCHI, [b, a])
    assert first is not None and second is not None
    assert first[0].branch_id == second[0].branch_id == B1


def test_nearest_workplace_empty() -> None:
    assert nearest_workplace(*KOCHI, []) is None


# --- policy modes ---------------------------------------------------------------------------


def test_disabled_ignores_location_entirely() -> None:
    decision = run(policy=DISABLED, location=loc(north_of(KOCHI, 9000)))
    assert decision.allowed and decision.enforced is False and decision.outcome == NOT_PROVIDED
    assert decision.distance_m is None


def test_required_without_location_is_refused() -> None:
    decision = run()
    assert decision.outcome == LOCATION_REQUIRED and decision.allowed is False


def test_required_with_client_reported_failure_is_refused_distinctly() -> None:
    decision = run(client_error="PERMISSION_DENIED")
    assert decision.outcome == LOCATION_UNAVAILABLE_CLIENT and decision.allowed is False


def test_optional_never_blocks_but_still_evaluates() -> None:
    outside = run(policy=OPTIONAL, location=loc(north_of(KOCHI, 5000)))
    assert outside.outcome == OUTSIDE_GEOFENCE
    assert outside.allowed is True and outside.enforced is False
    assert run(policy=OPTIONAL).outcome == NOT_PROVIDED
    assert run(policy=OPTIONAL).allowed is True
    assert run(policy=OPTIONAL, client_error="TIMEOUT").outcome == LOCATION_UNAVAILABLE_CLIENT
    assert run(policy=OPTIONAL, location=loc(), workplaces=[]).allowed is True


def test_same_inputs_always_give_the_same_decision() -> None:
    inputs = {"location": loc(north_of(KOCHI, 120), accuracy=25)}
    assert run(**inputs) == run(**inputs)


def test_round_coordinate_keeps_four_places() -> None:
    assert str(round_coordinate(9.931234567)) == "9.9312"
    assert str(round_coordinate(-76.267389)) == "-76.2674"
