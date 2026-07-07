from app.models.anomaly_state import ZoneBreachState, InactivityState


# --- ZoneBreachState ---

def test_zone_breach_fires_once_on_entry():
    state = ZoneBreachState()
    assert state.check_entry("tag-1", "zone-A") is True
    assert state.check_entry("tag-1", "zone-A") is False  # still inside, no re-fire
    assert state.check_entry("tag-1", "zone-A") is False


def test_zone_breach_refires_after_leaving_and_reentering():
    state = ZoneBreachState()
    assert state.check_entry("tag-1", "zone-A") is True
    assert state.check_entry("tag-1", None) is False  # left the zone
    assert state.check_entry("tag-1", "zone-A") is True  # re-entered - fires again


def test_zone_breach_moving_between_two_restricted_zones_fires_again():
    state = ZoneBreachState()
    assert state.check_entry("tag-1", "zone-A") is True
    assert state.check_entry("tag-1", "zone-B") is True  # different zone - new entry


def test_zone_breach_tracks_tags_independently():
    state = ZoneBreachState()
    assert state.check_entry("tag-1", "zone-A") is True
    assert state.check_entry("tag-2", "zone-A") is True  # different tag - independent state


def test_zone_breach_never_inside_stays_false():
    state = ZoneBreachState()
    assert state.check_entry("tag-1", None) is False
    assert state.check_entry("tag-1", None) is False


# --- InactivityState ---

def test_inactivity_no_alert_on_first_reading():
    state = InactivityState()
    assert state.check_inactivity("tag-1", 0.0, 0.0, now=1000.0, threshold_seconds=300) is False


def test_inactivity_fires_after_threshold_when_stationary():
    state = InactivityState()
    state.check_inactivity("tag-1", 0.0, 0.0, now=1000.0, threshold_seconds=300)
    # still near the same position, threshold not yet reached
    assert state.check_inactivity("tag-1", 0.05, 0.0, now=1100.0, threshold_seconds=300) is False
    # threshold now crossed
    assert state.check_inactivity("tag-1", 0.05, 0.0, now=1301.0, threshold_seconds=300) is True


def test_inactivity_does_not_refire_same_episode():
    state = InactivityState()
    state.check_inactivity("tag-1", 0.0, 0.0, now=1000.0, threshold_seconds=300)
    assert state.check_inactivity("tag-1", 0.0, 0.0, now=1301.0, threshold_seconds=300) is True
    assert state.check_inactivity("tag-1", 0.0, 0.0, now=1400.0, threshold_seconds=300) is False


def test_inactivity_resets_and_can_refire_after_movement():
    state = InactivityState()
    state.check_inactivity("tag-1", 0.0, 0.0, now=1000.0, threshold_seconds=300)
    assert state.check_inactivity("tag-1", 0.0, 0.0, now=1301.0, threshold_seconds=300) is True
    # moves well past the epsilon - resets the stillness clock and alert flag
    assert state.check_inactivity("tag-1", 10.0, 10.0, now=1302.0, threshold_seconds=300) is False
    # stays still again for a full threshold period - fires again
    assert state.check_inactivity("tag-1", 10.0, 10.0, now=1603.0, threshold_seconds=300) is True


def test_inactivity_small_jitter_within_epsilon_does_not_reset_clock():
    state = InactivityState()
    state.check_inactivity("tag-1", 0.0, 0.0, now=1000.0, threshold_seconds=300)
    # 0.3m jitter, under MOVEMENT_EPSILON_M default of 1.0 - should NOT reset the clock
    assert state.check_inactivity("tag-1", 0.3, 0.0, now=1301.0, threshold_seconds=300) is True


def test_inactivity_tracks_tags_independently():
    state = InactivityState()
    state.check_inactivity("tag-1", 0.0, 0.0, now=1000.0, threshold_seconds=300)
    assert state.check_inactivity("tag-1", 0.0, 0.0, now=1301.0, threshold_seconds=300) is True
    # tag-2's first reading - independent of tag-1's state
    assert state.check_inactivity("tag-2", 5.0, 5.0, now=1301.0, threshold_seconds=300) is False
