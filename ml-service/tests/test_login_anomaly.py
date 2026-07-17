import math

import pytest
from app.models.anomaly_state import LoginAnomalyState

def test_allows_normal_travel_speed():
    state = LoginAnomalyState()
    emp_id = "emp-123"
    
    # First login at t=0 (London Heathrow approx)
    is_anom1, details1 = state.check_travel_anomaly(emp_id, 51.4700, -0.4543, timestamp=1710000000)
    assert not is_anom1
    
    # Second login 2 hours later, 50 km away (Gatwick approx)
    # 50 km in 2 hours = 25 km/h (well below 900 km/h threshold)
    is_anom2, details2 = state.check_travel_anomaly(emp_id, 51.1537, -0.1821, timestamp=1710007200)
    assert not is_anom2

def test_flags_impossible_travel_velocity():
    state = LoginAnomalyState()
    emp_id = "emp-999"
    
    # First login at t=0 (London Heathrow)
    state.check_travel_anomaly(emp_id, 51.4700, -0.4543, timestamp=1710000000)
    
    # Second login 5 minutes (300s) later in New York (JFK: 40.6413, -73.7781)
    # Traveling across the Atlantic in 5 minutes is physically impossible
    is_anom, details = state.check_travel_anomaly(emp_id, 40.6413, -73.7781, timestamp=1710000300)
    
    assert is_anom
    assert "calculated_speed_kmh" in details
    assert details["calculated_speed_kmh"] > 900.0

def test_flags_concurrent_or_out_of_order_timestamps():
    state = LoginAnomalyState()
    emp_id = "emp-000"
    
    # First login
    state.check_travel_anomaly(emp_id, 51.4700, -0.4543, timestamp=1710000000)
    
    # Second login at the exact same timestamp but different coordinates
    is_anom, details = state.check_travel_anomaly(emp_id, 40.6413, -73.7781, timestamp=1710000000)
    
    assert is_anom
    assert "Concurrent login" in details["error"]

def test_first_ever_login_is_never_anomalous():
    """An employee's very first recorded login has nothing to compare
    against yet - there is no "previous location" to be impossibly far
    from, so this must always pass through as non-anomalous with no
    details, regardless of where in the world it comes from."""
    state = LoginAnomalyState()

    is_anom, details = state.check_travel_anomaly(
        "emp-first", 35.6762, 139.6503, timestamp=1710000000  # Tokyo
    )

    assert not is_anom
    assert details == {}

def test_exact_threshold_speed_is_not_anomalous():
    """calculated_speed_kmh == max_speed_kmh must NOT be flagged - the
    check is strictly-greater-than, so a login landing exactly on the
    configured threshold should not fire (only exceeding it should)."""
    state = LoginAnomalyState()
    emp_id = "emp-boundary"
    max_speed_kmh = 900.0

    # Two points ~500 km apart along a meridian (roughly 4.5 degrees of
    # latitude), timed so distance / time_delta_hours lands exactly on
    # max_speed_kmh - i.e. right at the boundary, not past it.
    lat1, lon1 = 51.4700, 0.0
    lat2, lon2 = 51.4700 - 4.5, 0.0

    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    a = math.sin(d_lat / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance_km = R * c
    time_delta_hours = distance_km / max_speed_kmh

    state.check_travel_anomaly(emp_id, lat1, lon1, timestamp=1710000000)
    is_anom, details = state.check_travel_anomaly(
        emp_id, lat2, lon2, timestamp=1710000000 + time_delta_hours * 3600
    )

    assert not is_anom
    assert details == {}
