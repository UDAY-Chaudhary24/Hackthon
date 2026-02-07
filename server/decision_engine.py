"""
APEX Decision Engine
Implements the exact priority calculation logic from the system blueprint
"""
import numpy as np
from typing import Dict, Tuple
from models import (
    LaneState, LaneDirection, SignalDecision, DecisionReason,
    VehicleCount
)
import time


class DecisionEngine:
    """
    Core decision-making logic for traffic signals
    Implements: Priority calculation → Softmax → Safety constraints
    """
    
    def __init__(self):
        # Safety constraints (hard rules)
        self.MAX_WAIT_TIME = 120.0  # seconds
        self.MIN_GREEN = 5.0  # seconds
        self.MAX_GREEN = 60.0  # seconds
        self.RECENT_GREEN_DECAY_WINDOW = 30.0  # seconds
        
        # Softmax temperature
        self.TEMPERATURE = 0.7  # τ ≈ 0.6-0.8 for strong but smooth preference
        
        # Vehicle weights (spatial cost)
        self.VEHICLE_WEIGHTS = {
            "car": 1.0,
            "bike": 0.3,  # Lower spatial cost
            "truck": 1.5,  # Higher spatial cost
            "bus": 1.5,
            "emergency": 10.0,  # Absolute priority
            "pedestrians": 0.5
        }
        
        # Rain adjustment (bikes get higher priority for safety)
        self.RAIN_BIKE_MULTIPLIER = 2.0
    
    
    def decide(self, lanes: Dict[LaneDirection, LaneState]) -> SignalDecision:
        """
        Main decision pipeline - EXACT ORDER from document:
        1. Emergency check
        2. Max wait violation
        3. Calculate priorities (local + downstream)
        4. Recent green decay
        5. Softmax probability
        6. Green time allocation
        """
        
        # 1. EMERGENCY CHECK (hard override)
        emergency_lane = self._check_emergency(lanes)
        if emergency_lane:
            return self._create_emergency_decision(emergency_lane, lanes)
        
        # 2. MAX WAIT VIOLATION (forced green)
        max_wait_lane = self._check_max_wait(lanes)
        if max_wait_lane:
            return self._create_forced_decision(max_wait_lane, lanes, "max_wait_violation")
        
        # 3. CALCULATE NET PRIORITY (local × downstream²)
        priorities = self._calculate_net_priorities(lanes)
        
        # 4. RECENT GREEN DECAY (penalize recently served lanes)
        priorities = self._apply_recent_green_decay(lanes, priorities)
        
        # 5. SOFTMAX PROBABILITY (fairness, prevent starvation)
        probabilities = self._softmax(priorities, self.TEMPERATURE)
        
        # 6. SELECT LANE (probabilistic selection)
        selected_lane = self._select_lane(probabilities)
        
        # 7. GREEN TIME ALLOCATION (based on traffic load)
        green_duration = self._calculate_green_duration(lanes[selected_lane])
        
        # 8. BUILD DECISION WITH REASON TRACE
        return self._create_decision(
            selected_lane, 
            green_duration, 
            lanes, 
            priorities, 
            probabilities
        )
    
    
    def _check_emergency(self, lanes: Dict[LaneDirection, LaneState]) -> LaneDirection | None:
        """Emergency check - absolute override"""
        for direction, lane in lanes.items():
            if lane.vision.ambulanceDetected:
                return direction
        return None
    
    
    def _check_max_wait(self, lanes: Dict[LaneDirection, LaneState]) -> LaneDirection | None:
        """Max wait violation check - forced green"""
        for direction, lane in lanes.items():
            if lane.waitTime > self.MAX_WAIT_TIME:
                return direction
        return None
    
    
    def _calculate_local_traffic_score(self, lane: LaneState) -> float:
        """
        Calculate local lane priority using vehicle weights
        Incorporates: vehicle types, rain conditions, speed
        """
        vehicles = lane.vision.vehicleCountByType
        
        # Base weighted sum
        score = (
            vehicles.car * self.VEHICLE_WEIGHTS["car"] +
            vehicles.bike * self.VEHICLE_WEIGHTS["bike"] +
            vehicles.truck * self.VEHICLE_WEIGHTS["truck"] +
            vehicles.bus * self.VEHICLE_WEIGHTS["bus"] +
            vehicles.emergency * self.VEHICLE_WEIGHTS["emergency"] +
            vehicles.pedestrians * self.VEHICLE_WEIGHTS["pedestrians"]
        )
        
        # Rain adjustment (bikes get higher priority)
        if lane.vision.rainDetected:
            score += vehicles.bike * self.VEHICLE_WEIGHTS["bike"] * (self.RAIN_BIKE_MULTIPLIER - 1)
        
        # Speed factor (slower = more congested = higher priority)
        # Normalize speed: 0 km/h → 1.0, 60 km/h → 0.0
        speed_factor = max(0, 1 - (lane.vision.avgSpeed / 60.0))
        score *= (1 + speed_factor)
        
        # Occupancy factor
        score *= (1 + lane.vision.laneOccupancy)
        
        return score
    
    
    def _calculate_downstream_priority(self, lane: LaneState) -> float:
        """
        Downstream impact calculation (user-proposed logic)
        Less downstream congestion → higher priority order
        """
        if not lane.downstream:
            return 1.0  # Neutral if no downstream data
        
        # Downstream congestion penalty
        # High downstream speed → low congestion → high priority
        # Low downstream speed → high congestion → low priority
        downstream_speed = lane.downstream.avgSpeed
        
        # Normalize: 60 km/h = 1.0 (free flow), 0 km/h = 0.1 (gridlock)
        priority_order = max(0.1, downstream_speed / 60.0)
        
        return priority_order
    
    
    def _calculate_net_priorities(self, lanes: Dict[LaneDirection, LaneState]) -> Dict[LaneDirection, float]:
        """
        NET PRIORITY FORMULA:
        netPriority = localTrafficScore × (downstreamPriorityOrder)²
        
        Why square? Downstream congestion is more dangerous than local congestion
        """
        priorities = {}
        
        for direction, lane in lanes.items():
            local_score = self._calculate_local_traffic_score(lane)
            downstream_priority = self._calculate_downstream_priority(lane)
            
            # Apply formula
            net_priority = local_score * (downstream_priority ** 2)
            priorities[direction] = net_priority
        
        return priorities
    
    
    def _apply_recent_green_decay(
        self, 
        lanes: Dict[LaneDirection, LaneState], 
        priorities: Dict[LaneDirection, float]
    ) -> Dict[LaneDirection, float]:
        """
        Penalize lanes that were recently served
        Prevents oscillation and flickering
        """
        current_time = time.time()
        adjusted_priorities = {}
        
        for direction, priority in priorities.items():
            lane = lanes[direction]
            time_since_green = current_time - lane.lastGreenTime
            
            # Decay factor: 0 = just served, 1 = not served recently
            if time_since_green < self.RECENT_GREEN_DECAY_WINDOW:
                decay = time_since_green / self.RECENT_GREEN_DECAY_WINDOW
            else:
                decay = 1.0
            
            adjusted_priorities[direction] = priority * decay
        
        return adjusted_priorities
    
    
    def _softmax(self, priorities: Dict[LaneDirection, float], temperature: float) -> Dict[LaneDirection, float]:
        """
        Convert priorities to probabilities using softmax
        Prevents starvation and oscillation
        """
        # Extract values in consistent order
        directions = list(priorities.keys())
        values = np.array([priorities[d] for d in directions])
        
        # Add small epsilon to avoid division by zero
        values = values + 1e-6
        
        # Apply temperature scaling
        scaled = values / temperature
        
        # Softmax
        exp_values = np.exp(scaled - np.max(scaled))  # Numerical stability
        probabilities = exp_values / np.sum(exp_values)
        
        # Convert back to dictionary
        return {d: p for d, p in zip(directions, probabilities)}
    
    
    def _select_lane(self, probabilities: Dict[LaneDirection, float]) -> LaneDirection:
        """
        Select lane based on softmax probabilities
        Allows fairness while respecting priorities
        """
        directions = list(probabilities.keys())
        probs = [probabilities[d] for d in directions]
        
        selected_idx = np.random.choice(len(directions), p=probs)
        return directions[selected_idx]
    
    
    def _calculate_green_duration(self, lane: LaneState) -> float:
        """
        Calculate green signal duration based on traffic load
        Bounded by MIN_GREEN and MAX_GREEN
        """
        # Base duration proportional to traffic
        local_score = self._calculate_local_traffic_score(lane)
        
        # Normalize to 5-60 second range
        # Assume max score of 50 vehicles equivalent
        normalized = min(local_score / 50.0, 1.0)
        duration = self.MIN_GREEN + (self.MAX_GREEN - self.MIN_GREEN) * normalized
        
        # Low confidence → reduce duration
        duration *= lane.vision.confidenceScore
        
        return max(self.MIN_GREEN, min(self.MAX_GREEN, duration))
    
    
    def _create_decision(
        self,
        lane: LaneDirection,
        duration: float,
        lanes: Dict[LaneDirection, LaneState],
        priorities: Dict[LaneDirection, float],
        probabilities: Dict[LaneDirection, float]
    ) -> SignalDecision:
        """Create decision with full reason trace"""
        
        reason = DecisionReason(
            emergency=False,
            maxWaitViolation=False,
            downstreamPenalty=1.0 - self._calculate_downstream_priority(lanes[lane]),
            recentGreenDecay=1.0,  # Already applied
            softmaxProbability=probabilities[lane],
            localTrafficScore=self._calculate_local_traffic_score(lanes[lane])
        )
        
        return SignalDecision(
            selectedLane=lane,
            greenDuration=duration,
            decisionConfidence=probabilities[lane],
            reasonTrace=reason,
            timestamp=time.time()
        )
    
    
    def _create_emergency_decision(self, lane: LaneDirection, lanes: Dict[LaneDirection, LaneState]) -> SignalDecision:
        """Emergency override - max green, hard lock"""
        
        reason = DecisionReason(
            emergency=True,
            maxWaitViolation=False,
            downstreamPenalty=0.0,
            recentGreenDecay=1.0,
            softmaxProbability=1.0,
            localTrafficScore=999.0
        )
        
        return SignalDecision(
            selectedLane=lane,
            greenDuration=self.MAX_GREEN,
            decisionConfidence=1.0,
            reasonTrace=reason,
            timestamp=time.time()
        )
    
    
    def _create_forced_decision(
        self, 
        lane: LaneDirection, 
        lanes: Dict[LaneDirection, LaneState],
        reason_type: str
    ) -> SignalDecision:
        """Forced decision due to safety constraint violation"""
        
        reason = DecisionReason(
            emergency=False,
            maxWaitViolation=(reason_type == "max_wait_violation"),
            downstreamPenalty=0.0,
            recentGreenDecay=1.0,
            softmaxProbability=1.0,
            localTrafficScore=self._calculate_local_traffic_score(lanes[lane])
        )
        
        return SignalDecision(
            selectedLane=lane,
            greenDuration=self.MIN_GREEN,  # Quick clear
            decisionConfidence=1.0,
            reasonTrace=reason, 
            timestamp=time.time()
        )