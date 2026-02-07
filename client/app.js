// Traffic simulation state
let simulationRunning = false;
let currentMode = 'ai'; // 'ai' or 'manual'
let emergencyMode = false;
let simulationSpeed = 1;

let lanes = [
    { name: 'North', vehicles: 0, canvas: null, ctx: null },
    { name: 'South', vehicles: 0, canvas: null, ctx: null },
    { name: 'East', vehicles: 0, canvas: null, ctx: null },
    { name: 'West', vehicles: 0, canvas: null, ctx: null }
];

let currentSignal = 0; // 0 = North-South green, 1 = East-West green
let signalTimer = 30;
let totalCycles = 0;
let totalWaitTime = 0;
let co2Saved = 0;

// Vehicle type tracking
let vehicleTypes = {
    cars: 0,
    buses: 0,
    bikes: 0,
    trucks: 0,
    emergency: 0,
    pedestrians: 0
};

// Performance history for chart
let performanceHistory = [];
let maxHistoryLength = 30;

// Weather conditions
const weatherConditions = [
    { icon: '☀️', temp: 28, condition: 'Clear Sky', factor: 1.0 },
    { icon: '⛅', temp: 25, condition: 'Partly Cloudy', factor: 1.1 },
    { icon: '☁️', temp: 22, condition: 'Cloudy', factor: 1.2 },
    { icon: '🌧️', temp: 20, condition: 'Rainy', factor: 1.5 },
    { icon: '⛈️', temp: 18, condition: 'Stormy', factor: 2.0 }
];
let currentWeather = weatherConditions[0];

// ============================================================================
// BACKEND INTEGRATION (NEW - APEX System)
// ============================================================================

const BACKEND_URL = 'http://localhost:8000';
let backendConnected = false;
let lastBackendCallTime = 0;
const BACKEND_CALL_INTERVAL = 5000; // Call backend every 5 seconds

// Track wait times for each lane
let laneWaitTimes = {
    'North': 0,
    'South': 0,
    'East': 0,
    'West': 0
};

let lastGreenTimes = {
    'North': Date.now() / 1000,
    'South': Date.now() / 1000,
    'East': Date.now() / 1000,
    'West': Date.now() / 1000
};

// Check backend connection
async function checkBackendConnection() {
    try {
        const response = await fetch(`${BACKEND_URL}/health`);
        if (response.ok) {
            backendConnected = true;
            addLog('✅ Backend connected - AI mode active');
            return true;
        }
    } catch (error) {
        backendConnected = false;
        addLog('⚠️ Backend offline - using local logic');
        return false;
    }
}

// Convert lane data to backend format
function createLaneState(lane) {
    // Calculate average speed based on vehicle density
    // More vehicles = slower speed
    const density = lane.vehicles / 8;
    const avgSpeed = Math.max(5, 60 * (1 - density)); // 5-60 km/h
    
    // Calculate lane occupancy
    const occupancy = Math.min(1.0, lane.vehicles / 8);
    
    // Check for rain
    const rainDetected = currentWeather.condition === 'Rainy' || currentWeather.condition === 'Stormy';
    
    // Build vision output
    return {
        direction: lane.name,
        vision: {
            vehicleCountByType: {
                car: Math.floor(vehicleTypes.cars / 4), // Distribute across lanes
                bike: Math.floor(vehicleTypes.bikes / 4),
                truck: Math.floor(vehicleTypes.trucks / 4),
                bus: Math.floor(vehicleTypes.buses / 4),
                emergency: vehicleTypes.emergency > 0 ? 1 : 0,
                pedestrians: Math.floor(vehicleTypes.pedestrians / 4)
            },
            avgSpeed: avgSpeed,
            laneOccupancy: occupancy,
            ambulanceDetected: emergencyMode && lane.name === lanes[Math.floor(Math.random() * 4)].name,
            rainDetected: rainDetected,
            confidenceScore: 0.95
        },
        downstream: {
            avgSpeed: 40 + Math.random() * 20, // Simulated downstream speed
            congestionIndex: Math.random() * 0.5,
            ttl: 60
        },
        waitTime: laneWaitTimes[lane.name],
        lastGreenTime: lastGreenTimes[lane.name]
    };
}

// Call backend decision engine
async function getBackendDecision() {
    if (!backendConnected || currentMode !== 'ai') {
        return null;
    }
    
    // Rate limiting: don't call too frequently
    const now = Date.now();
    if (now - lastBackendCallTime < BACKEND_CALL_INTERVAL) {
        return null;
    }
    lastBackendCallTime = now;
    
    try {
        // Build intersection state
        const intersectionState = {
            lanes: {},
            currentSignal: currentSignal === 0 ? 'North' : 'East',
            emergencyMode: emergencyMode
        };
        
        // Add all lane states
        lanes.forEach(lane => {
            intersectionState.lanes[lane.name] = createLaneState(lane);
        });
        
        // Make API call
        const response = await fetch(`${BACKEND_URL}/api/decision`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                intersectionState: intersectionState,
                controlMode: 'ai'
            })
        });
        
        if (!response.ok) {
            throw new Error(`Backend error: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Log decision details
        if (data.decision) {
            const decision = data.decision;
            addLog(`🤖 AI Decision: ${decision.selectedLane} for ${decision.greenDuration.toFixed(1)}s (confidence: ${(decision.decisionConfidence * 100).toFixed(0)}%)`);
            
            // Log reasoning
            if (decision.reasonTrace.emergency) {
                addLog('   Reason: Emergency override');
            } else if (decision.reasonTrace.maxWaitViolation) {
                addLog('   Reason: Max wait time exceeded');
            } else {
                addLog(`   Reason: Traffic score ${decision.reasonTrace.localTrafficScore.toFixed(1)}, Probability ${(decision.reasonTrace.softmaxProbability * 100).toFixed(0)}%`);
            }
        }
        
        return data;
        
    } catch (error) {
        console.error('Backend call failed:', error);
        addLog('⚠️ Backend call failed - using fallback logic');
        backendConnected = false;
        return null;
    }
}

// Apply backend decision to signals
function applyBackendDecision(decision) {
    if (!decision || !decision.decision) return;
    
    const selectedLane = decision.decision.selectedLane;
    const duration = Math.round(decision.decision.greenDuration);
    
    // Map lane name to signal index
    let newSignal;
    if (selectedLane === 'North' || selectedLane === 'South') {
        newSignal = 0; // North-South green
    } else {
        newSignal = 1; // East-West green
    }
    
    // Only switch if different
    if (newSignal !== currentSignal) {
        currentSignal = newSignal;
        signalTimer = duration;
        totalCycles++;
        
        const direction = currentSignal === 0 ? 'North-South' : 'East-West';
        addLog(`🚦 Signal switched: ${direction} green for ${duration}s`);
        
        // Update last green time for the activated lanes
        const now = Date.now() / 1000;
        if (currentSignal === 0) {
            lastGreenTimes['North'] = now;
            lastGreenTimes['South'] = now;
            laneWaitTimes['North'] = 0;
            laneWaitTimes['South'] = 0;
        } else {
            lastGreenTimes['East'] = now;
            lastGreenTimes['West'] = now;
            laneWaitTimes['East'] = 0;
            laneWaitTimes['West'] = 0;
        }
    } else {
        // Extend current signal
        signalTimer = duration;
    }
}

// Update wait times for lanes
function updateWaitTimes() {
    // Increment wait time for lanes that are red
    if (currentSignal === 0) {
        // North-South is green, East-West is waiting
        laneWaitTimes['East']++;
        laneWaitTimes['West']++;
    } else {
        // East-West is green, North-South is waiting
        laneWaitTimes['North']++;
        laneWaitTimes['South']++;
    }
}

// ============================================================================
// END BACKEND INTEGRATION
// ============================================================================

// Initialize canvases
function initCanvases() {
    for (let i = 0; i < 4; i++) {
        const canvas = document.getElementById(`camera${i + 1}`);
        const ctx = canvas.getContext('2d');
        canvas.width = 400;
        canvas.height = 225;
        lanes[i].canvas = canvas;
        lanes[i].ctx = ctx;
    }
}

// Draw traffic scene
function drawTrafficScene(lane, index) {
    const ctx = lane.ctx;
    const canvas = lane.canvas;
    
    // Clear canvas
    ctx.fillStyle = '#1a1f3a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Draw road
    ctx.fillStyle = '#2a2f4a';
    ctx.fillRect(0, canvas.height * 0.4, canvas.width, canvas.height * 0.3);
    
    // Draw lane markings
    ctx.strokeStyle = '#ffbe0b';
    ctx.lineWidth = 2;
    ctx.setLineDash([20, 15]);
    ctx.beginPath();
    ctx.moveTo(0, canvas.height * 0.55);
    ctx.lineTo(canvas.width, canvas.height * 0.55);
    ctx.stroke();
    ctx.setLineDash([]);
    
    // Draw vehicles
    const vehicleWidth = 30;
    const vehicleHeight = 20;
    const spacing = 40;
    
    for (let i = 0; i < lane.vehicles; i++) {
        const x = 50 + (i * spacing);
        const y = canvas.height * 0.5 - vehicleHeight / 2;
        
        // Vehicle body
        ctx.fillStyle = `hsl(${(i * 30) % 360}, 70%, 60%)`;
        ctx.fillRect(x, y, vehicleWidth, vehicleHeight);
        
        // Vehicle windows
        ctx.fillStyle = 'rgba(0, 212, 255, 0.3)';
        ctx.fillRect(x + 5, y + 3, vehicleWidth - 10, vehicleHeight - 6);
        
        // Headlights
        ctx.fillStyle = '#ffbe0b';
        ctx.fillRect(x + vehicleWidth - 3, y + 2, 2, 5);
        ctx.fillRect(x + vehicleWidth - 3, y + vehicleHeight - 7, 2, 5);
    }
    
    // Draw traffic density indicator with car icons
    const density = lane.vehicles / 8;
    const barWidth = canvas.width * 0.15;
    const barHeight = 10;
    const barX = canvas.width - barWidth - 10;
    const barY = 10;
    
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.fillRect(barX, barY, barWidth, barHeight);
    
    let barColor;
    if (density < 0.3) barColor = '#00ff9d';
    else if (density < 0.7) barColor = '#ffbe0b';
    else barColor = '#ff006e';
    
    ctx.fillStyle = barColor;
    ctx.fillRect(barX, barY, barWidth * density, barHeight);
    
    // Draw small car icons on the density bar
    const carIconWidth = 12;
    const carIconHeight = 8;
    const carIconY = barY + 1;
    const maxCars = 8;
    const carSpacing = barWidth / maxCars;
    
    for (let i = 0; i < lane.vehicles && i < maxCars; i++) {
        const carX = barX + (i * carSpacing) + 2;
        
        // Car body
        ctx.fillStyle = `hsl(${(i * 45) % 360}, 80%, 65%)`;
        ctx.fillRect(carX, carIconY, carIconWidth, carIconHeight);
        
        // Car window
        ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
        ctx.fillRect(carX + 2, carIconY + 1, carIconWidth - 4, carIconHeight - 3);
        
        // Headlights
        ctx.fillStyle = '#ffbe0b';
        ctx.fillRect(carX + carIconWidth - 2, carIconY + 1, 1, 2);
        ctx.fillRect(carX + carIconWidth - 2, carIconY + carIconHeight - 3, 1, 2);
    }
}

// Update vehicle counts randomly
function updateTrafficDensity() {
    // Reset vehicle types
    vehicleTypes = { cars: 0, buses: 0, bikes: 0, trucks: 0, emergency: 0, pedestrians: 0 };
    
    lanes.forEach((lane, index) => {
        // Simulate traffic flow with weather impact
        const weatherImpact = currentWeather.factor;
        const change = Math.floor((Math.random() * 3 - 1) * weatherImpact);
        lane.vehicles = Math.max(0, Math.min(8, lane.vehicles + change));
        
        // Randomly assign vehicle types
        vehicleTypes.cars += Math.floor(lane.vehicles * 0.5);
        vehicleTypes.bikes += Math.floor(lane.vehicles * 0.2);
        vehicleTypes.buses += Math.floor(lane.vehicles * 0.1);
        vehicleTypes.trucks += Math.floor(lane.vehicles * 0.1);
        
        // Update UI
        document.getElementById(`count${index + 1}`).textContent = `${lane.vehicles} vehicles`;
        drawTrafficScene(lane, index);
    });
    
    // Random pedestrians
    vehicleTypes.pedestrians = Math.floor(Math.random() * 20);
    
    // Update vehicle type display
    document.getElementById('carCount').textContent = vehicleTypes.cars;
    document.getElementById('busCount').textContent = vehicleTypes.buses;
    document.getElementById('bikeCount').textContent = vehicleTypes.bikes;
    document.getElementById('truckCount').textContent = vehicleTypes.trucks;
    document.getElementById('emergencyCount').textContent = vehicleTypes.emergency;
    document.getElementById('pedestrianCount').textContent = vehicleTypes.pedestrians;
}

// Set control mode
function setMode(mode) {
    currentMode = mode;
    document.getElementById('aiModeBtn').classList.toggle('active', mode === 'ai');
    document.getElementById('manualModeBtn').classList.toggle('active', mode === 'manual');
    
    if (mode === 'ai') {
        addLog('Switched to AI automatic mode');
        checkBackendConnection(); // Check backend when switching to AI mode
    } else {
        addLog('Switched to manual override mode');
    }
}

// Trigger emergency vehicle
function triggerEmergency() {
    if (!simulationRunning) {
        addLog('Start simulation first to trigger emergency');
        return;
    }
    
    emergencyMode = true;
    vehicleTypes.emergency++;
    document.getElementById('emergencyCount').textContent = vehicleTypes.emergency;
    document.getElementById('emergencyAlert').classList.add('active');
    
    // Override signal for emergency
    const emergencyLane = Math.floor(Math.random() * 4);
    const direction = emergencyLane < 2 ? 'North-South' : 'East-West';
    currentSignal = emergencyLane < 2 ? 0 : 1;
    signalTimer = 60; // Extended time for emergency
    
    addLog(`🚨 Emergency vehicle detected in ${lanes[emergencyLane].name} lane`);
    addLog(`Priority green light activated for ${direction}`);
    
    setTimeout(() => {
        emergencyMode = false;
        vehicleTypes.emergency = Math.max(0, vehicleTypes.emergency - 1);
        document.getElementById('emergencyCount').textContent = vehicleTypes.emergency;
        document.getElementById('emergencyAlert').classList.remove('active');
        addLog('Emergency vehicle cleared - resuming normal operation');
    }, 10000);
}

// Add traffic manually
function addTraffic() {
    lanes.forEach(lane => {
        lane.vehicles = Math.min(8, lane.vehicles + Math.floor(Math.random() * 3));
    });
    addLog('Manual traffic surge added to all lanes');
    updateTrafficDensity();
}

// Draw traffic heatmap
function drawHeatmap() {
    const canvas = document.getElementById('heatmapCanvas');
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    
    // Clear canvas
    ctx.fillStyle = '#1a1f3a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Draw intersection
    const centerX = canvas.width / 2;
    const centerY = canvas.height / 2;
    const roadWidth = 80;
    
    // Horizontal road
    ctx.fillStyle = '#2a2f4a';
    ctx.fillRect(0, centerY - roadWidth/2, canvas.width, roadWidth);
    
    // Vertical road
    ctx.fillRect(centerX - roadWidth/2, 0, roadWidth, canvas.height);
    
    // Draw heatmap for each direction
    const directions = [
        { x: centerX, y: centerY - 100, width: 60, height: 80, lane: 0, label: 'N' },
        { x: centerX, y: centerY + 20, width: 60, height: 80, lane: 1, label: 'S' },
        { x: centerX + 20, y: centerY, width: 80, height: 60, lane: 2, label: 'E' },
        { x: centerX - 100, y: centerY, width: 80, height: 60, lane: 3, label: 'W' }
    ];
    
    directions.forEach(dir => {
        const density = lanes[dir.lane].vehicles / 8;
        let color;
        if (density < 0.3) color = 'rgba(0, 255, 157, 0.6)';
        else if (density < 0.7) color = 'rgba(255, 190, 11, 0.6)';
        else color = 'rgba(255, 0, 110, 0.6)';
        
        ctx.fillStyle = color;
        ctx.fillRect(dir.x - dir.width/2, dir.y - dir.height/2, dir.width, dir.height);
        
        // Label
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 20px Rajdhani';
        ctx.textAlign = 'center';
        ctx.fillText(dir.label, dir.x, dir.y + 7);
    });
    
    // Draw signal indicators
    const signal1Color = currentSignal === 0 ? '#00ff9d' : '#ff006e';
    const signal2Color = currentSignal === 1 ? '#00ff9d' : '#ff006e';
    
    ctx.fillStyle = signal1Color;
    ctx.beginPath();
    ctx.arc(centerX, centerY - 50, 8, 0, Math.PI * 2);
    ctx.fill();
    
    ctx.fillStyle = signal2Color;
    ctx.beginPath();
    ctx.arc(centerX + 50, centerY, 8, 0, Math.PI * 2);
    ctx.fill();
}

// Draw performance chart
function drawPerformanceChart() {
    const canvas = document.getElementById('performanceChart');
    const ctx = canvas.getContext('2d');
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    
    // Clear canvas
    ctx.fillStyle = '#1a1f3a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    if (performanceHistory.length < 2) return;
    
    // Draw grid
    ctx.strokeStyle = 'rgba(0, 255, 157, 0.1)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
        const y = (canvas.height / 5) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
    }
    
    // Draw efficiency line
    ctx.strokeStyle = '#00ff9d';
    ctx.lineWidth = 2;
    ctx.beginPath();
    
    const spacing = canvas.width / (maxHistoryLength - 1);
    performanceHistory.forEach((value, index) => {
        const x = index * spacing;
        const y = canvas.height - (value / 100 * canvas.height);
        
        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();
    
    // Draw glow effect
    ctx.strokeStyle = 'rgba(0, 255, 157, 0.3)';
    ctx.lineWidth = 4;
    ctx.stroke();
}

// Update weather
function updateWeather() {
    if (Math.random() < 0.1) { // 10% chance to change weather
        currentWeather = weatherConditions[Math.floor(Math.random() * weatherConditions.length)];
        document.getElementById('weatherIcon').textContent = currentWeather.icon;
        document.getElementById('weatherTemp').textContent = `${currentWeather.temp}°C`;
        document.getElementById('weatherCondition').textContent = currentWeather.condition;
        
        addLog(`Weather changed: ${currentWeather.condition}`);
    }
}

// Update predictions
function updatePredictions() {
    const totalTraffic = lanes.reduce((sum, lane) => sum + lane.vehicles, 0);
    
    // Peak forecast
    let peakLevel = 'Low';
    if (totalTraffic > 20) peakLevel = 'High';
    else if (totalTraffic > 12) peakLevel = 'Medium';
    document.getElementById('peakForecast').textContent = peakLevel;
    
    // Congestion risk
    const congestionRisk = Math.min(95, Math.floor((totalTraffic / 32) * 100));
    document.getElementById('congestionRisk').textContent = `${congestionRisk}%`;
    
    // Optimal route
    const nsTraffic = lanes[0].vehicles + lanes[1].vehicles;
    const ewTraffic = lanes[2].vehicles + lanes[3].vehicles;
    const optimalRoute = nsTraffic < ewTraffic ? 'North-South' : 'East-West';
    document.getElementById('optimalRoute').textContent = optimalRoute;
}

// AI-based signal optimization (LOCAL FALLBACK)
function optimizeSignals() {
    const nsTraffic = lanes[0].vehicles + lanes[1].vehicles;
    const ewTraffic = lanes[2].vehicles + lanes[3].vehicles;
    
    let greenTime;
    if (currentSignal === 0) {
        // North-South is green
        if (nsTraffic > ewTraffic * 2) {
            greenTime = 45; // More time for heavier traffic
        } else if (nsTraffic < ewTraffic / 2) {
            greenTime = 20; // Less time if light traffic
        } else {
            greenTime = 30; // Default
        }
    } else {
        // East-West is green
        if (ewTraffic > nsTraffic * 2) {
            greenTime = 45;
        } else if (ewTraffic < nsTraffic / 2) {
            greenTime = 20;
        } else {
            greenTime = 30;
        }
    }
    
    return greenTime;
}

// Update signal lights
function updateSignals() {
    const signal1 = document.getElementById('signal1');
    const signal2 = document.getElementById('signal2');
    const timer1 = document.getElementById('timer1');
    const timer2 = document.getElementById('timer2');
    
    if (currentSignal === 0) {
        signal1.className = 'signal-light active-green';
        signal2.className = 'signal-light active-red';
        timer1.textContent = `${signalTimer}s`;
        timer2.textContent = 'STOP';
    } else {
        signal1.className = 'signal-light active-red';
        signal2.className = 'signal-light active-green';
        timer1.textContent = 'STOP';
        timer2.textContent = `${signalTimer}s`;
    }
}

// Add log entry
function addLog(message) {
    const logPanel = document.getElementById('logPanel');
    const time = new Date().toLocaleTimeString();
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `<span class="log-time">[${time}]</span>${message}`;
    logPanel.insertBefore(entry, logPanel.firstChild);
    
    // Keep only last 10 entries
    while (logPanel.children.length > 10) {
        logPanel.removeChild(logPanel.lastChild);
    }
}

// Update statistics
function updateStats() {
    const totalVehicles = lanes.reduce((sum, lane) => sum + lane.vehicles, 0);
    document.getElementById('totalVehicles').textContent = totalVehicles;
    
    const avgWait = emergencyMode ? 5 : Math.floor(15 + Math.random() * 10 * currentWeather.factor);
    totalWaitTime += avgWait;
    document.getElementById('avgWait').textContent = `${avgWait}s`;
    
    const baseEfficiency = currentMode === 'ai' ? 70 : 50;
    const efficiency = Math.min(100, Math.floor(baseEfficiency + totalCycles * 1.5 + Math.random() * 10 - (currentWeather.factor - 1) * 20));
    document.getElementById('efficiency').textContent = `${efficiency}%`;
    
    // Add to performance history
    performanceHistory.push(efficiency);
    if (performanceHistory.length > maxHistoryLength) {
        performanceHistory.shift();
    }
    
    co2Saved += (0.5 + Math.random() * 0.3) * (efficiency / 100);
    document.getElementById('emissions').textContent = `${co2Saved.toFixed(1)}kg`;
}

// Main simulation loop (MODIFIED WITH BACKEND INTEGRATION)
async function runSimulation() {
    if (!simulationRunning) return;
    
    // Update traffic every second
    updateTrafficDensity();
    updateStats();
    updateWeather();
    updatePredictions();
    updateWaitTimes(); // Track wait times for backend
    drawHeatmap();
    drawPerformanceChart();
    
    // Countdown signal timer
    signalTimer--;
    
    if (signalTimer <= 0 && !emergencyMode) {
        // Time to make a decision
        
        if (currentMode === 'ai' && backendConnected) {
            // Try to get backend decision
            const backendDecision = await getBackendDecision();
            
            if (backendDecision) {
                // Apply backend decision
                applyBackendDecision(backendDecision);
            } else {
                // Fallback to local logic
                currentSignal = 1 - currentSignal;
                signalTimer = optimizeSignals();
                totalCycles++;
                
                const direction = currentSignal === 0 ? 'North-South' : 'East-West';
                addLog(`Local AI: ${direction} green for ${signalTimer}s`);
            }
        } else {
            // Manual mode or backend offline - use local logic
            currentSignal = 1 - currentSignal;
            
            if (currentMode === 'ai') {
                signalTimer = optimizeSignals();
            } else {
                signalTimer = 30; // Fixed time in manual mode
            }
            
            totalCycles++;
            
            const direction = currentSignal === 0 ? 'North-South' : 'East-West';
            const modeText = currentMode === 'ai' ? 'Local AI' : 'Manual';
            addLog(`${modeText}: ${direction} green for ${signalTimer}s`);
        }
    }
    
    updateSignals();
    
    setTimeout(runSimulation, 1000 / simulationSpeed);
}

// Start simulation (MODIFIED)
async function startSimulation() {
    if (simulationRunning) return;
    
    simulationRunning = true;
    signalTimer = 30;
    currentSignal = 0;
    
    addLog('AI Traffic Optimizer activated');
    addLog('Analyzing real-time traffic patterns...');
    
    // Check backend connection
    if (currentMode === 'ai') {
        await checkBackendConnection();
    }
    
    runSimulation();
}

// Stop simulation
function stopSimulation() {
    if (!simulationRunning) return;
    
    simulationRunning = false;
    addLog('AI Traffic Optimizer paused');
}

// Speed slider
document.getElementById('speedSlider')?.addEventListener('input', function(e) {
    simulationSpeed = parseInt(e.target.value);
    document.getElementById('speedValue').textContent = `${simulationSpeed}x`;
    addLog(`Simulation speed changed to ${simulationSpeed}x`);
});

// Initialize
window.onload = function() {
    initCanvases();
    
    // Set initial random traffic
    lanes.forEach((lane, index) => {
        lane.vehicles = Math.floor(Math.random() * 5) + 1;
        drawTrafficScene(lane, index);
        document.getElementById(`count${index + 1}`).textContent = `${lane.vehicles} vehicles`;
    });
    
    updateSignals();
    updateTrafficDensity();
    drawHeatmap();
    drawPerformanceChart();
    addLog('System initialized. Ready to start.');
    
    // Check backend on startup
    checkBackendConnection();
};