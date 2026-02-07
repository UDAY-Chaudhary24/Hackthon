"""
Data contracts for APEX Traffic Signal Optimizer
Follows the strict layering from the system blueprint
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict
from enum import Enum


class VehicleType(str, Enum):
    """Vehicle types detected by vision system"""
    CAR = "car"
    BIKE = "bike"
    TRUCK = "truck"
    BUS = "bus"
    EMERGENCY = "emergency"


class LaneDirection(str, Enum):
    """Lane directions in the intersection"""
    NORTH = "North"
    SOUTH = "South"
    EAST = "East"
    WEST = "West"


# ============================================================================
# VISION LAYER OUTPUT (Camera → Features)
# ============================================================================

class VehicleCount(BaseModel):
    """Vehicle count by type - from YOLO detection"""
    car: int = 0
    bike: int = 0
    truck: int = 0
    bus: int = 0
    emergency: int = 0
    pedestrians: int = 0


class VisionOutput(BaseModel):
    """
    VISION OUTPUT CONTRACT (VERY IMPORTANT)
    The vision system outputs ONLY this - no decisions, no priorities
    """
    vehicleCountByType: VehicleCount
    avgSpeed: float = Field(ge=0, le=100, description="Average speed in km/h, decreases with congestion")
    laneOccupancy: float = Field(ge=0, le=1, description="How full the lane is (0-1)")
    ambulanceDetected: bool = False
    rainDetected: bool = False
    confidenceScore: float = Field(ge=0, le=1, default=0.95)


# ============================================================================
# MAPS LAYER OUTPUT (Downstream awareness)
# ============================================================================

class DownstreamData(BaseModel):
    """
    Maps integration data
    Provides downstream congestion awareness
    """
    avgSpeed: float = Field(ge=0, le=100, description="Downstream average speed")
    congestionIndex: float = Field(ge=0, le=1, description="0 = free flow, 1 = gridlock")
    ttl: int = Field(default=60, description="Data freshness in seconds")


# ============================================================================
# LANE STATE (Combined vision + maps)
# ============================================================================

class LaneState(BaseModel):
    """
    Complete state of a single lane
    Combines vision output + downstream data
    """
    direction: LaneDirection
    vision: VisionOutput
    downstream: Optional[DownstreamData] = None
    waitTime: float = Field(default=0, description="Seconds since last green")
    lastGreenTime: float = Field(default=0, description="Timestamp of last green signal")


# ============================================================================
# DECISION ENGINE OUTPUT (Backend → Frontend)
# ============================================================================

class DecisionReason(BaseModel):
    """Explainability trace for decision"""
    emergency: bool = False
    maxWaitViolation: bool = False
    downstreamPenalty: float = 0.0
    recentGreenDecay: float = 0.0
    softmaxProbability: float = 0.0
    localTrafficScore: float = 0.0


class SignalDecision(BaseModel):
    """
    BACKEND OUTPUT CONTRACT
    What the decision engine returns to frontend
    """
    selectedLane: LaneDirection
    greenDuration: float = Field(ge=5, le=120, description="Green signal duration in seconds")
    decisionConfidence: float = Field(ge=0, le=1)
    reasonTrace: DecisionReason
    timestamp: float


# ============================================================================
# REQUEST/RESPONSE MODELS
# ============================================================================

class IntersectionState(BaseModel):
    """
    Complete intersection state sent from frontend
    Contains all 4 lanes
    """
    lanes: Dict[LaneDirection, LaneState]
    currentSignal: Optional[LaneDirection] = None
    emergencyMode: bool = False


class DecisionRequest(BaseModel):
    """Request from frontend to backend"""
    intersectionState: IntersectionState
    controlMode: str = Field(default="ai", pattern="^(ai|manual)$")


class DecisionResponse(BaseModel):
    """Response from backend to frontend"""
    decision: SignalDecision
    fallbackMode: bool = False
    errorMessage: Optional[str] = None