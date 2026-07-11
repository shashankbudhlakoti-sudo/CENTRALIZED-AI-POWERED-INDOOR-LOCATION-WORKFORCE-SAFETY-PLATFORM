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
