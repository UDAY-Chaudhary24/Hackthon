"""
APEX Traffic Signal Optimizer - Backend Server
FastAPI application with decision endpoint
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import (
    DecisionRequest, DecisionResponse, SignalDecision,
    IntersectionState, LaneDirection, LaneState
)
from decision_engine import DecisionEngine
from maps_adapter import get_maps_adapter
import logging
from typing import Dict
import time
# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="APEX Traffic Signal Optimizer",
    description="AI-powered traffic signal decision system",
    version="1.0.0"
)

# CORS middleware (allow frontend at localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize decision engine
decision_engine = DecisionEngine()

# Initialize maps adapter
maps_adapter = get_maps_adapter()


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "APEX Traffic Signal Optimizer",
        "status": "operational",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "decision_engine": "ready",
        "endpoints": {
            "decision": "/api/decision",
            "health": "/health"
        }
    }


@app.post("/api/decision", response_model=DecisionResponse)
async def make_decision(request: DecisionRequest):
    """
    Main decision endpoint
    
    Receives intersection state from frontend
    Returns signal decision with reasoning trace
    
    Pipeline:
    1. Validate input
    2. Run decision engine
    3. Return decision with explainability
    """
    try:
        logger.info(f"Received decision request - Mode: {request.controlMode}")
        
        # Only process in AI mode
        if request.controlMode != "ai":
            raise HTTPException(
                status_code=400, 
                detail="Backend only processes AI mode requests"
            )
        
        # Extract intersection state
        intersection = request.intersectionState
        
        # Validate we have lanes
        if not intersection.lanes:
            raise HTTPException(
                status_code=400,
                detail="No lane data provided"
            )
        
        # Log lane states
        for direction, lane in intersection.lanes.items():
            logger.info(
                f"Lane {direction}: "
                f"Cars={lane.vision.vehicleCountByType.car}, "
                f"Speed={lane.vision.avgSpeed:.1f} km/h, "
                f"Wait={lane.waitTime:.1f}s"
            )
        
        # Enrich with real/simulated maps data
        weather = "Clear Sky"  # Default, can be passed from frontend
        for direction, lane in intersection.lanes.items():
            # Get downstream traffic data from maps
            downstream_data = maps_adapter.get_downstream_traffic(
                direction, 
                weather_condition=weather
            )
            # Update lane state with fresh downstream data
            lane.downstream = downstream_data
            
            logger.info(
                f"Downstream {direction}: "
                f"Speed={downstream_data.avgSpeed:.1f} km/h, "
                f"Congestion={downstream_data.congestionIndex:.2f}"
            )
        
        # Run decision engine
        decision = decision_engine.decide(intersection.lanes)
        
        # Log decision
        logger.info(
            f"Decision: {decision.selectedLane} for {decision.greenDuration:.1f}s "
            f"(confidence: {decision.decisionConfidence:.2f})"
        )
        logger.info(f"Reason: {decision.reasonTrace}")
        
        # Return response
        return DecisionResponse(
            decision=decision,
            fallbackMode=False,
            errorMessage=None
        )
    
    except HTTPException:
        raise
    
    except Exception as e:
        logger.error(f"Decision engine error: {str(e)}", exc_info=True)
        
        # Fallback: return safe decision
        fallback_decision = _create_fallback_decision(request.intersectionState)
        
        return DecisionResponse(
            decision=fallback_decision,
            fallbackMode=True,
            errorMessage=f"Error: {str(e)}. Using fallback logic."
        )


def _create_fallback_decision(intersection: IntersectionState) -> SignalDecision:
    """
    Fallback decision logic (fixed-time)
    Used when decision engine fails
    """
    from models import DecisionReason
    import time
    
    # Simple round-robin: pick first lane with vehicles
    for direction, lane in intersection.lanes.items():
        total_vehicles = (
            lane.vision.vehicleCountByType.car +
            lane.vision.vehicleCountByType.truck +
            lane.vision.vehicleCountByType.bus
        )
        if total_vehicles > 0:
            return SignalDecision(
                selectedLane=direction,
                greenDuration=15.0,  # Fixed 15 seconds
                decisionConfidence=0.5,
                reasonTrace=DecisionReason(
                    emergency=False,
                    maxWaitViolation=False,
                    downstreamPenalty=0.0,
                    recentGreenDecay=1.0,
                    softmaxProbability=0.5,
                    localTrafficScore=float(total_vehicles)
                ),
                timestamp=time.time()
            )
    
    # If no vehicles anywhere, default to North
    return SignalDecision(
        selectedLane=LaneDirection.NORTH,
        greenDuration=10.0,
        decisionConfidence=0.5,
        reasonTrace=DecisionReason(
            emergency=False,
            maxWaitViolation=False,
            downstreamPenalty=0.0,
            recentGreenDecay=1.0,
            softmaxProbability=0.25,
            localTrafficScore=0.0
        ),
        timestamp=time.time()
    )


@app.get("/api/traffic/summary")
async def get_traffic_summary():
    """
    Get current traffic summary for all downstream roads
    Useful for monitoring and debugging
    """
    try:
        summary = maps_adapter.get_traffic_summary()
        return {
            "status": "success",
            "timestamp": time.time(),
            "traffic": summary
        }
    except Exception as e:
        logger.error(f"Error getting traffic summary: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/traffic/accident")
async def trigger_accident(lane: str, duration_minutes: int = 30):
    """
    Manually trigger an accident for testing
    
    Args:
        lane: "North", "South", "East", or "West"
        duration_minutes: How long the accident lasts (default 30 min)
    """
    try:
        # Convert string to LaneDirection enum
        lane_direction = LaneDirection[lane.upper()]
        maps_adapter.trigger_accident(lane_direction, duration_minutes)
        
        logger.info(f"Accident triggered on {lane} for {duration_minutes} minutes")
        
        return {
            "status": "success",
            "message": f"Accident triggered on downstream of {lane} lane",
            "duration_minutes": duration_minutes
        }
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid lane: {lane}. Must be North, South, East, or West"
        )
    except Exception as e:
        logger.error(f"Error triggering accident: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/traffic/clear-accidents")
async def clear_accidents():
    """Clear all active accidents"""
    try:
        maps_adapter.clear_accidents()
        logger.info("All accidents cleared")
        return {
            "status": "success",
            "message": "All accidents cleared"
        }
    except Exception as e:
        logger.error(f"Error clearing accidents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    
    logger.info("Starting APEX Traffic Signal Optimizer Backend...")
    logger.info("Frontend should be at: http://localhost:3000")
    logger.info("Backend API docs: http://localhost:8000/docs")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,  # Auto-reload on code changes
        log_level="info"
    )