"""
Maps Adapter for APEX Traffic Signal Optimizer
Provides downstream traffic awareness with realistic simulation

This module can be easily swapped with real APIs:
- Google Maps Distance Matrix API
- TomTom Traffic Flow API
- HERE Traffic API
"""
import time
import random
from datetime import datetime
from typing import Dict, Optional, Tuple
from models import DownstreamData, LaneDirection
import math


class MapsAdapter:
    """
    Provides downstream traffic data for decision making
    
    Current implementation: Realistic simulation
    Future: Can be replaced with actual Maps API calls
    """
    
    def __init__(self, simulation_mode: bool = True):
        self.simulation_mode = simulation_mode
        
        # Simulated road network (downstream from each lane)
        # In reality, these would be actual road segment IDs
        self.downstream_roads = {
            LaneDirection.NORTH: "road_north_downtown",
            LaneDirection.SOUTH: "road_south_highway",
            LaneDirection.EAST: "road_east_residential",
            LaneDirection.WEST: "road_west_industrial"
        }
        
        # Cache for reducing API calls (60 second TTL)
        self.cache = {}
        self.cache_ttl = 60
        
        # Accident simulation
        self.active_accidents = {}
        self.accident_probability = 0.02  # 2% chance per minute
        
        # Weather impact multiplier
        self.weather_impact = 1.0
    
    
    def get_downstream_traffic(
        self, 
        lane: LaneDirection,
        weather_condition: Optional[str] = None
    ) -> DownstreamData:
        """
        Get downstream traffic conditions for a lane
        
        Args:
            lane: Which lane to check downstream from
            weather_condition: Current weather (affects traffic)
            
        Returns:
            DownstreamData with speed, congestion, TTL
        """
        
        # Check cache first
        cache_key = f"{lane.value}_{weather_condition}"
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                return cached_data
        
        # Get traffic data (simulated or real)
        if self.simulation_mode:
            data = self._simulate_downstream_traffic(lane, weather_condition)
        else:
            data = self._fetch_real_traffic_data(lane)
        
        # Cache the result
        self.cache[cache_key] = (data, time.time())
        
        return data
    
    
    def _simulate_downstream_traffic(
        self, 
        lane: LaneDirection,
        weather_condition: Optional[str] = None
    ) -> DownstreamData:
        """
        Simulate realistic downstream traffic patterns
        
        Factors considered:
        - Time of day (rush hour vs off-peak)
        - Day of week (weekday vs weekend)
        - Weather conditions
        - Random accidents/incidents
        - Road characteristics (highway vs residential)
        """
        
        now = datetime.now()
        hour = now.hour
        day_of_week = now.weekday()  # 0=Monday, 6=Sunday
        
        # Base speed by road type
        road_type_speeds = {
            LaneDirection.NORTH: 45,  # Downtown - moderate
            LaneDirection.SOUTH: 70,  # Highway - fast
            LaneDirection.EAST: 35,   # Residential - slow
            LaneDirection.WEST: 50    # Industrial - moderate-fast
        }
        
        base_speed = road_type_speeds.get(lane, 50)
        
        # Time of day impact (rush hours)
        time_factor = self._get_time_of_day_factor(hour, day_of_week)
        
        # Weather impact
        weather_factor = self._get_weather_factor(weather_condition)
        
        # Random variation (traffic is never perfectly predictable)
        random_factor = random.uniform(0.85, 1.15)
        
        # Check for accidents on this route
        accident_factor = self._check_accidents(lane)
        
        # Calculate final speed
        final_speed = base_speed * time_factor * weather_factor * random_factor * accident_factor
        final_speed = max(5, min(100, final_speed))  # Clamp to 5-100 km/h
        
        # Calculate congestion index (inverse of speed)
        # 0 = free flow (high speed), 1 = gridlock (very low speed)
        max_speed = base_speed * 1.2  # Best case speed
        congestion_index = 1 - (final_speed / max_speed)
        congestion_index = max(0, min(1, congestion_index))
        
        return DownstreamData(
            avgSpeed=round(final_speed, 1),
            congestionIndex=round(congestion_index, 2),
            ttl=self.cache_ttl
        )
    
    
    def _get_time_of_day_factor(self, hour: int, day_of_week: int) -> float:
        """
        Calculate traffic factor based on time of day
        
        Rush hours (7-9 AM, 5-7 PM on weekdays): Heavy traffic
        Midday (10 AM - 4 PM): Moderate traffic
        Night (10 PM - 6 AM): Light traffic
        Weekends: Generally lighter traffic
        """
        
        # Weekend traffic is generally lighter
        is_weekend = day_of_week >= 5  # Saturday=5, Sunday=6
        
        if is_weekend:
            # Weekends: lighter traffic, but some congestion during day
            if 10 <= hour <= 20:  # Daytime
                return random.uniform(0.8, 0.95)
            else:  # Night
                return random.uniform(0.95, 1.1)
        
        # Weekday patterns
        if 7 <= hour <= 9:  # Morning rush hour
            return random.uniform(0.4, 0.6)  # Heavy congestion
        
        elif 17 <= hour <= 19:  # Evening rush hour
            return random.uniform(0.3, 0.5)  # Very heavy congestion
        
        elif 10 <= hour <= 16:  # Midday
            return random.uniform(0.7, 0.9)  # Moderate traffic
        
        elif 22 <= hour or hour <= 5:  # Night/early morning
            return random.uniform(1.0, 1.2)  # Light traffic
        
        else:  # Other times
            return random.uniform(0.8, 1.0)
    
    
    def _get_weather_factor(self, weather_condition: Optional[str]) -> float:
        """
        Calculate traffic slowdown due to weather
        
        Clear: Normal speeds
        Rain: 10-20% slower
        Storm: 30-50% slower
        """
        
        if not weather_condition:
            return 1.0
        
        weather_lower = weather_condition.lower()
        
        if 'storm' in weather_lower or 'heavy rain' in weather_lower:
            return random.uniform(0.5, 0.7)  # 30-50% slower
        
        elif 'rain' in weather_lower or 'drizzle' in weather_lower:
            return random.uniform(0.8, 0.9)  # 10-20% slower
        
        elif 'fog' in weather_lower:
            return random.uniform(0.7, 0.85)  # 15-30% slower
        
        elif 'snow' in weather_lower:
            return random.uniform(0.4, 0.6)  # 40-60% slower
        
        else:  # Clear, cloudy, etc.
            return 1.0
    
    
    def _check_accidents(self, lane: LaneDirection) -> float:
        """
        Simulate random accidents/incidents that cause congestion
        
        Accidents:
        - Have a small random chance to occur
        - Last for 15-45 minutes
        - Significantly reduce speeds
        """
        
        current_time = time.time()
        road_id = self.downstream_roads[lane]
        
        # Check if there's an active accident
        if road_id in self.active_accidents:
            accident_end_time = self.active_accidents[road_id]
            
            if current_time < accident_end_time:
                # Accident still active - major slowdown
                return random.uniform(0.2, 0.4)  # 60-80% slower
            else:
                # Accident cleared
                del self.active_accidents[road_id]
                return 1.0
        
        # Random chance of new accident
        if random.random() < self.accident_probability / 60:  # Per second probability
            # Create new accident (lasts 15-45 minutes)
            duration = random.randint(15 * 60, 45 * 60)
            self.active_accidents[road_id] = current_time + duration
            return random.uniform(0.2, 0.4)
        
        return 1.0
    
    
    def _fetch_real_traffic_data(self, lane: LaneDirection) -> DownstreamData:
        """
        Fetch real traffic data from Maps API
        
        This is a placeholder for when you want to use real APIs:
        - Google Maps Distance Matrix API
        - TomTom Traffic Flow API
        - HERE Traffic API
        
        Example implementation for Google Maps:
        
        import requests
        
        API_KEY = "your_api_key"
        origin = self.intersection_coords
        destination = self.downstream_coords[lane]
        
        url = f"https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{destination[0]},{destination[1]}",
            "departure_time": "now",
            "traffic_model": "best_guess",
            "key": API_KEY
        }
        
        response = requests.get(url, params=params)
        data = response.json()
        
        # Extract travel time and speed
        duration = data['rows'][0]['elements'][0]['duration_in_traffic']['value']
        distance = data['rows'][0]['elements'][0]['distance']['value']
        speed = (distance / duration) * 3.6  # Convert m/s to km/h
        
        # Calculate congestion
        free_flow_duration = data['rows'][0]['elements'][0]['duration']['value']
        congestion_index = (duration - free_flow_duration) / free_flow_duration
        
        return DownstreamData(
            avgSpeed=speed,
            congestionIndex=max(0, min(1, congestion_index)),
            ttl=60
        )
        """
        
        # For now, fall back to simulation
        return self._simulate_downstream_traffic(lane, None)
    
    
    def set_weather(self, weather_condition: str):
        """Update weather condition for traffic simulation"""
        # Clear cache when weather changes
        self.cache.clear()
    
    
    def trigger_accident(self, lane: LaneDirection, duration_minutes: int = 30):
        """
        Manually trigger an accident for testing
        
        Args:
            lane: Which downstream road to affect
            duration_minutes: How long the accident lasts
        """
        road_id = self.downstream_roads[lane]
        self.active_accidents[road_id] = time.time() + (duration_minutes * 60)
        self.cache.clear()  # Clear cache to force update
    
    
    def clear_accidents(self):
        """Clear all active accidents"""
        self.active_accidents.clear()
        self.cache.clear()
    
    
    def get_traffic_summary(self) -> Dict[str, Dict]:
        """
        Get current traffic summary for all lanes
        Useful for debugging and monitoring
        """
        summary = {}
        
        for lane in LaneDirection:
            data = self.get_downstream_traffic(lane)
            
            # Classify traffic level
            if data.congestionIndex < 0.3:
                level = "Light"
            elif data.congestionIndex < 0.6:
                level = "Moderate"
            elif data.congestionIndex < 0.8:
                level = "Heavy"
            else:
                level = "Gridlock"
            
            summary[lane.value] = {
                "speed": data.avgSpeed,
                "congestion": data.congestionIndex,
                "level": level,
                "has_accident": self.downstream_roads[lane] in self.active_accidents
            }
        
        return summary


# Singleton instance
_maps_adapter_instance = None

def get_maps_adapter() -> MapsAdapter:
    """Get singleton instance of maps adapter"""
    global _maps_adapter_instance
    if _maps_adapter_instance is None:
        _maps_adapter_instance = MapsAdapter(simulation_mode=True)
    return _maps_adapter_instance