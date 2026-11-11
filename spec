--[[
	Spec
	----
	The single source of truth for what a vehicle *is*.

	A vehicle is described by a small set of human-scale parameters (peak torque, ride
	frequency, brake strength in g, ...). `Spec.build` turns those parameters plus the
	measured chassis geometry into the low-level stats table the physics runs on
	(torque curve points, spring constants, brake torques, sound layers, ...).

	Everything that can be derived is derived, so changing the mass re-rates the springs and
	brakes, changing the wheel size keeps the gearing honest, and dropping a new set of
	engine loops into CarSounds is enough to get crossfaded engine audio.

	Units: SI unless the name says otherwise. Roblox distances are converted with STUD.
]]

local Spec = {}

Spec.STUD = 0.28 -- metres per stud
Spec.KG_TO_RMU = 2853 / 1500 -- Roblox mass units per kilogram (calibrated against the stock body)
Spec.N_TO_FORCE = Spec.KG_TO_RMU / Spec.STUD -- newtons -> Roblox force units
Spec.DRIVE_GRAVITY = 40 -- studs/s^2 the car is simulated under
Spec.G = 9.81
Spec.WHEEL_DENSITY = 70 -- stock unsprung mass is heavy on purpose; it keeps the car planted
Spec.TIRE_DEFLECTION = 0.115 -- static tire deflection as a fraction of the radius
Spec.TIRE_DAMPING = 0.134 -- tire damping ratio
Spec.INERTIA_PER_R2 = 2.604 -- wheel inertia = k * r^2 (kg); keeps wheel dynamics radius independent

-- Geometry of the stock body. Used for read-outs before a car exists and as the
-- reference the default tune was calibrated against.
Spec.REFERENCE_GEOMETRY = {
	wheelbase = 14.174,
	trackFront = 7.591,
	trackRear = 7.230,
	radiusFront = 1.638,
	radiusRear = 1.638,
	widthFront = 1.30,
	widthRear = 1.30,
	strutCosFront = 0.964,
	strutCosRear = 0.995,
}

local function clone(value)
	if type(value) ~= "table" then
		return value
	end
	local copy = {}
	for key, inner in pairs(value) do
		copy[key] = clone(inner)
	end
	return copy
end
Spec.clone = clone

------------------------------------------------------------------------------------------
-- Sound defaults (everything that is not generated from engine packs)
------------------------------------------------------------------------------------------

Spec.DEFAULT_SOUNDS = {
	engine = {
		idle = { id = "rbxassetid://136307885787958", volume = 1, pitchMin = 0.95, pitchMax = 1.05 },
		limiter = { id = "rbxassetid://0", volume = 0.9, pitchFollowsRPM = false },
		start = { id = "rbxassetid://0", volume = 1 },
		stop = { id = "rbxassetid://0", volume = 0.8 },
		pitchMin = 0.6,
		pitchMax = 2.2,
		loadCrossfadeTime = 0.12,
	},
	intake = { id = "rbxassetid://0", refRPM = 4000, volumeByThrottle = { [0] = 0.05, [0.5] = 0.3, [1] = 0.6 }, volume = 0.5 },
	exhaust = {
		id = "rbxassetid://0",
		refRPM = 3500,
		volumeByThrottle = { [0] = 0.2, [0.5] = 0.6, [1] = 1 },
		volume = 0.8,
		pops = {
			ids = { "rbxassetid://0", "rbxassetid://0", "rbxassetid://0", "rbxassetid://0" },
			minRPM = 3500,
			throttleLiftBelow = 0.05,
			chance = 0.35,
			volume = 0.7,
			pitchVariation = 0.15,
		},
	},
	turbo = {
		spool = { id = "rbxassetid://0", pitchMin = 0.7, pitchMax = 2.4, volumeMin = 0, volumeMax = 0.5, spoolUpTime = 0.6, spoolDownTime = 1.2 },
		blowoff = { id = "rbxassetid://0", volume = 0.8, minBoost = 0.4, throttleLiftBelow = 0.1, cooldown = 0.5 },
		flutter = { ids = { "rbxassetid://0", "rbxassetid://0" }, volume = 0.7, chance = 0.5 },
	},
	driveline = {
		gearWhine = {
			id = "rbxassetid://0",
			refWheelRPM = 800,
			pitchMin = 0.5,
			pitchMax = 3,
			volumeOnPower = 0.35,
			volumeOnCoast = 0.2,
			perGearPitchMult = { [1] = 1.6, [2] = 1.25, [3] = 1.05, [4] = 0.9, [5] = 0.8 },
			perGearVolumeMult = { [1] = 1, [2] = 0.85, [3] = 0.7, [4] = 0.55, [5] = 0.5 },
			reverse = { pitchMult = 1.7, volumeMult = 1.2 },
		},
		diffWhine = { id = "rbxassetid://0", refWheelRPM = 800, pitchMin = 0.5, pitchMax = 2.5, volume = 0.2 },
		shiftClunk = { ids = { "rbxassetid://0", "rbxassetid://0" }, volume = 0.6 },
		clutchEngage = { id = "rbxassetid://0", volume = 0.4 },
		driveshaftRumble = { id = "rbxassetid://0", volume = 0.15 },
	},
	tires = {
		squeal = { id = "skid_long_noise.wav", slipStart = 0.4, slipFull = 0.9, pitchMin = 0.9, pitchMax = 1.3, volume = 0.8 },
		skidLoose = { id = "skid_long_hq.wav", slipStart = 0.5, volume = 0.7 },
		roadRoll = {
			asphalt = { id = "concrete.mp3", refSpeed = 25, pitchMin = 0.6, pitchMax = 1.6, volume = 0.1 },
			gravel = { id = "gravel_fine.mp3", refSpeed = 25, pitchMin = 0.7, pitchMax = 1.5, volume = 0.6 },
			grass = { id = "gravel_fine.mp3", refSpeed = 25, pitchMin = 0.7, pitchMax = 1.4, volume = 0.4 },
			dirt = { id = "dirt.mp3", refSpeed = 25, pitchMin = 0.7, pitchMax = 1.5, volume = 0.5 },
		},
		kickup = { id = "rbxassetid://0", minSpeed = 8, volume = 0.3 },
	},
	brakes = {
		squeal = { id = "rbxassetid://115235942061332", minSpeed = 3, maxSpeed = 15, minBrake = 0.5, volume = 0.35 },
		handbrake = { id = "rbxassetid://0", volume = 0.6 },
		absChatter = { id = "rbxassetid://0", volume = 0.5 },
	},
	body = {
		wind = { id = "wind.wav", refSpeed = 45, pitchMin = 0.6, pitchMax = 1.8, volumeMin = 0, volumeMax = 0.7 },
		suspensionBump = { ids = { "rbxassetid://0", "rbxassetid://0", "rbxassetid://0" }, minCompressionSpeed = 0.6, volume = 0.5 },
		bottomOut = { id = "rbxassetid://0", volume = 0.9 },
		impacts = { light = "rbxassetid://0", medium = "rbxassetid://0", heavy = "rbxassetid://0" },
		rattle = { id = "rbxassetid://0", refRPM = 2500, volume = 0.1 },
	},
	interior = {
		door = { open = "rbxassetid://0", close = "rbxassetid://0" },
		ignition = { id = "rbxassetid://0" },
		seatbelt = { id = "rbxassetid://0" },
		indicator = { on = "rbxassetid://0", off = "rbxassetid://0" },
	},
	mix = {
		exteriorLowpassHz = 20000,
		interiorLowpassHz = 2800,
		interiorVolumeMult = 0.7,
		rollOffMin = 12,
		rollOffMax = 350,
		reverbType = "Plain",
	},
}

Spec.DEFAULT_CAMERA = {
	advanced = {
		distance = 20, height = 2.6, pitch = 0.32,
		followRate = 1.4, offsetRate = 6, focusRate = 8, leadRate = 6,
		speedRef = 300, speedPullback = 6, fovSpeedRef = 260, maxLookAhead = 3,
		accelRef = 30, accelOffset = 1.2,
		fovBase = 68, fovSpeed = 10, fovAccel = 4, fovAccelRef = 35, fovRate = 3,
		shakeStart = 1.2, shakeScale = 0.25, shakeMax = 0.12,
	},
	simple = {
		distance = 18, height = 2.6, camHeight = 3.5,
		followRate = 2, offsetRate = 7,
		fov = 70, fovRate = 3,
	},
	racing = {
		distance = 12, height = 1.2, camHeight = 2.2,
		followRate = 4, offsetRate = 16,
		speedRef = 240, speedCurve = 1.6, pullback = 1.5,
		fovBase = 72, fovSpeed = 16, fovAccel = 3, fovRate = 4,
		accelRef = 40, accelBack = 1.2, accelPitchDeg = 2.5,
		leanRoll = 2.5, latRef = 80, leanRate = 5, leanSpeed = 30,
		steerYawDeg = 2.5, driftFollow = 0.5, maxDriftYawDeg = 12,
		bumpGain = 0.0015, bumpAccelClamp = 250, bumpMax = 0.35, bumpStiff = 140, bumpDamp = 14, bumpPitchDeg = 2.5,
		impactThreshold = 120, impactRange = 400, impactShakeDeg = 2.5, impactDecay = 8,
		shakeBase = 0.02, shakeSpeed = 0.5, shakeFreq = 7, shakeRotDeg = 1.2, shakePos = 0.08, roughness = 0.06,
		slipStart = 1.2, slipShake = 0.5,
	},
}

------------------------------------------------------------------------------------------
-- Generators
------------------------------------------------------------------------------------------

-- Parametric torque curve. Rises from `lowEnd * peak` at idle with a smooth power law,
-- holds the peak for `plateau` rpm, then falls off quadratically to `topEnd * peak`.
function Spec.shapedCurve(peak, peakRpm, plateau, idle, redline, lowEnd, topEnd)
	peakRpm = math.clamp(peakRpm, idle + 100, redline)
	local holdEnd = math.min(peakRpm + plateau, redline)
	local function torqueAt(rpm)
		if rpm <= peakRpm then
			local u = math.clamp((rpm - idle) / math.max(peakRpm - idle, 1), 0, 1)
			return peak * (lowEnd + (1 - lowEnd) * (1 - (1 - u) ^ 2.5))
		elseif rpm <= holdEnd then
			return peak
		end
		local v = math.clamp((rpm - holdEnd) / math.max(redline - holdEnd, 1), 0, 1)
		return peak * (1 - (1 - topEnd) * v * v)
	end

	local points = {}
	local step = 250
	local rpm = idle
	while rpm < redline do
		table.insert(points, { rpm = rpm, torque = torqueAt(rpm) })
		rpm = math.floor(rpm / step + 1) * step
	end
	table.insert(points, { rpm = redline, torque = torqueAt(redline) })
	-- make sure the exact peak and plateau end are represented
	for _, key in ipairs({ peakRpm, holdEnd }) do
		local present = false
		for _, p in ipairs(points) do
			if math.abs(p.rpm - key) < 1 then
				present = true
			end
		end
		if not present and key > idle and key < redline then
			table.insert(points, { rpm = key, torque = torqueAt(key) })
		end
	end
	table.sort(points, function(a, b)
		return a.rpm < b.rpm
	end)
	return points
end

-- Gear set from first/top ratios. spread = 0 gives geometric steps, higher values pack
-- the upper gears closer together (the way road cars are usually geared).
function Spec.generateGears(count, first, top, spread)
	count = math.clamp(math.floor(count + 0.5), 1, 10)
	if count == 1 then
		return { first }
	end
	local gaps = count - 1
	local weights, total = {}, 0
	for i = 0, gaps - 1 do
		local w = 1 + spread * (gaps - 1 - i) / math.max(gaps - 1, 1)
		weights[i + 1] = w
		total += w
	end
	local span = math.log(first / math.max(top, 0.01))
	local gears = { first }
	local ratio = first
	for i = 1, gaps do
		ratio = ratio / math.exp(span * weights[i] / total)
		gears[i + 1] = math.floor(ratio * 100 + 0.5) / 100
	end
	return gears
end

-- Engine loop packs: any set of >= 3 sounds named <prefix><rpm><suffix>.
local function parseLoop(name)
	local base = name:gsub("%.%w+$", "")
	local prefix, digits, tail = base:match("^(.-)(%d+)(%a*)$")
	if not prefix then
		return nil
	end
	local rpm = tonumber(digits)
	if not rpm or rpm < 300 or rpm > 25000 then
		return nil
	end
	return prefix, rpm, tail
end

function Spec.detectPacks(names)
	local packs, byKey = {}, {}
	for _, name in ipairs(names) do
		local prefix, rpm, tail = parseLoop(name)
		if prefix then
			local key = prefix .. "#" .. tail
			local pack = byKey[key]
			if not pack then
				local label = prefix:gsub("[_%-%s]+$", "")
				if label == "" then
					label = "loops"
				end
				pack = { key = key, prefix = prefix, tail = tail, label = label, layers = {} }
				byKey[key] = pack
				table.insert(packs, pack)
			end
			table.insert(pack.layers, { rpm = rpm, name = name })
		end
	end
	local result = {}
	for _, pack in ipairs(packs) do
		if #pack.layers >= 3 then
			table.sort(pack.layers, function(a, b)
				return a.rpm < b.rpm
			end)
			table.insert(result, pack)
		end
	end
	table.sort(result, function(a, b)
		return a.label < b.label
	end)
	return result
end

local function packScore(pack, role)
	local p = string.lower(pack.prefix)
	local onHint = p:match("p$") or p:find("on", 1, true) or p:find("power", 1, true) or p:find("accel", 1, true)
	local offHint = p:match("f$") or p:find("off", 1, true) or p:find("coast", 1, true) or p:find("decel", 1, true)
	local score = #pack.layers
	if role == "on" then
		if offHint then
			score -= 100
		end
		if onHint then
			score += 50
		end
	else
		if offHint then
			score += 100
		end
	end
	return score
end

function Spec.pickPack(packs, role, wanted)
	if wanted and wanted ~= "auto" then
		for _, pack in ipairs(packs) do
			if pack.key == wanted or pack.label == wanted then
				return pack
			end
		end
	end
	local best, bestScore
	for _, pack in ipairs(packs) do
		local score = packScore(pack, role)
		if not best or score > bestScore then
			best, bestScore = pack, score
		end
	end
	return best
end

-- Crossfaded layers: each loop fades out over the upper part of the gap to the next one
-- while the next fades in, using equal-power curves in the physics.
function Spec.buildLayers(pack, volLow, volHigh)
	local layers = {}
	if not pack then
		return layers
	end
	local list = pack.layers
	local n = #list
	for i, layer in ipairs(list) do
		local prev, nxt = list[i - 1], list[i + 1]
		local entry = {
			id = layer.name,
			refRPM = layer.rpm,
			fadeInStart = 0,
			fadeInEnd = 0,
			fadeOutStart = 99999,
			fadeOutEnd = 99999,
			volume = volLow + (volHigh - volLow) * ((i - 1) / math.max(n - 1, 1)),
		}
		if prev then
			entry.fadeInStart = prev.rpm + (layer.rpm - prev.rpm) * 0.45
			entry.fadeInEnd = layer.rpm
		end
		if nxt then
			entry.fadeOutStart = layer.rpm + (nxt.rpm - layer.rpm) * 0.45
			entry.fadeOutEnd = nxt.rpm
		end
		layers[i] = entry
	end
	return layers
end

------------------------------------------------------------------------------------------
-- Parameter schema
------------------------------------------------------------------------------------------

Spec.sections = {
	{ id = "engine", label = "Engine" },
	{ id = "gearing", label = "Gearing" },
	{ id = "chassis", label = "Chassis" },
	{ id = "suspension", label = "Suspension" },
	{ id = "tires", label = "Tires" },
	{ id = "brakes", label = "Brakes" },
	{ id = "aero", label = "Aero" },
	{ id = "assists", label = "Assists" },
	{ id = "camera", label = "Camera" },
	{ id = "sound", label = "Sound" },
}

Spec.params = {}
Spec.byId = {}

local function def(section, group, t)
	t.section = section
	t.group = group
	t.tier = t.tier or "basic"
	t.kind = t.kind or "number"
	table.insert(Spec.params, t)
	Spec.byId[t.id] = t
end

local DIFFS = { "OPEN", "LIMITED", "TORSEN", "CLUTCH_LSD", "LOCKED", "WELDED" }

-- Engine
def("engine", "Output", { id = "engine.peakTorque", label = "Peak torque", unit = "Nm", default = 350, min = 50, max = 2000, step = 5, hint = "Torque at the top of the curve." })
def("engine", "Output", { id = "engine.peakRpm", label = "Peak torque at", unit = "rpm", default = 3950, min = 1000, max = 12000, step = 50 })
def("engine", "Output", { id = "engine.redline", label = "Redline", unit = "rpm", default = 7500, min = 2000, max = 14000, step = 100, hint = "Rev limiter engages here." })
def("engine", "Curve shape", { id = "engine.curveMode", label = "Curve", kind = "enum", options = { "Shaped", "Custom" }, default = "Shaped", tier = "advanced", hint = "Shaped builds the curve from the sliders. Custom uses the point list." })
def("engine", "Curve shape", { id = "engine.plateau", label = "Peak plateau", unit = "rpm", default = 550, min = 0, max = 5000, step = 50, tier = "advanced" })
def("engine", "Curve shape", { id = "engine.lowEnd", label = "Torque at idle", unit = "%", default = 0.43, min = 0.05, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("engine", "Curve shape", { id = "engine.topEnd", label = "Torque at redline", unit = "%", default = 0.657, min = 0.05, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("engine", "Curve shape", { id = "engine.curve", label = "Custom points", kind = "curve", default = nil, tier = "advanced" })
def("engine", "Idle", { id = "engine.idle", label = "Idle", unit = "rpm", default = 800, min = 300, max = 2500, step = 25, tier = "advanced" })
def("engine", "Idle", { id = "engine.idleAuthority", label = "Idle controller", default = 0.4, min = 0, max = 1, step = 0.01, tier = "advanced" })
def("engine", "Idle", { id = "engine.stallRpm", label = "Stall below", unit = "rpm", default = 550, min = 100, max = 2000, step = 25, tier = "advanced" })
def("engine", "Internals", { id = "engine.inertia", label = "Flywheel inertia", unit = "kg·m²", default = 0.18, min = 0.02, max = 2, step = 0.01, tier = "advanced", hint = "Lower revs up faster." })
def("engine", "Internals", { id = "engine.frictionStatic", label = "Static friction", unit = "Nm", default = 16, min = 0, max = 100, step = 0.5, tier = "advanced" })
def("engine", "Internals", { id = "engine.frictionViscous", label = "Viscous friction", default = 0.010, min = 0, max = 0.2, step = 0.001, tier = "advanced" })
def("engine", "Internals", { id = "engine.pumping", label = "Pumping loss", default = 0.0010, min = 0, max = 0.01, step = 0.0001, tier = "advanced" })
def("engine", "Internals", { id = "engine.accessory", label = "Accessory load", unit = "Nm", default = 6, min = 0, max = 60, step = 0.5, tier = "advanced" })
def("engine", "Limiter", { id = "engine.limiterRpm", label = "Limiter", unit = "rpm", min = 1000, max = 15000, step = 50, tier = "advanced", auto = function(ctx)
	return ctx.get("engine.redline")
end })
def("engine", "Limiter", { id = "engine.limiterCut", label = "Cut strength", default = 1, min = 0, max = 1, step = 0.05, tier = "advanced" })
def("engine", "Limiter", { id = "engine.limiterHysteresis", label = "Hysteresis", unit = "rpm", default = 150, min = 0, max = 1000, step = 10, tier = "advanced" })

-- Gearing
def("gearing", "Transmission", { id = "gearbox.mode", label = "Gearbox", kind = "enum", options = { "MANUAL", "ASSISTED", "AUTOMATIC" }, labels = { "Manual", "Assisted", "Auto" }, default = "MANUAL" })
def("gearing", "Transmission", { id = "drivetrain.layout", label = "Driven wheels", kind = "enum", options = { "RWD", "FWD", "AWD" }, default = "RWD" })
def("gearing", "Transmission", { id = "gearbox.gears", label = "Gear ratios", kind = "gears", default = { 3.90, 2.40, 1.68, 1.30, 1.04 } })
def("gearing", "Transmission", { id = "gearbox.finalDrive", label = "Final drive", default = 3.61, min = 1, max = 9, step = 0.01, hint = "Higher = quicker acceleration, lower top speed." })
def("gearing", "Transmission", { id = "gearbox.reverse", label = "Reverse", default = 3.89, min = 1, max = 8, step = 0.01, tier = "advanced" })
def("gearing", "Transmission", { id = "gearbox.shiftTime", label = "Shift time", unit = "s", default = 0.10, min = 0, max = 1, step = 0.01, tier = "advanced" })
def("gearing", "Transmission", { id = "gearbox.efficiency", label = "Efficiency", unit = "%", default = 0.97, min = 0.5, max = 1, step = 0.005, display = "percent", tier = "advanced" })
def("gearing", "Transmission", { id = "clutch.maxTorque", label = "Clutch capacity", unit = "Nm", min = 50, max = 4000, step = 10, tier = "advanced", auto = function(ctx)
	return math.floor(ctx.get("engine.peakTorque") * 1.37 / 10 + 0.5) * 10
end })
def("gearing", "Differential", { id = "drivetrain.diff", label = "Differential", kind = "enum", options = DIFFS, labels = { "Open", "LSD", "Torsen", "Clutch LSD", "Locked", "Welded" }, default = "OPEN" })
def("gearing", "Differential", { id = "drivetrain.preload", label = "Preload", unit = "Nm", default = 15, min = 0, max = 500, step = 1, tier = "advanced" })
def("gearing", "Differential", { id = "drivetrain.powerLock", label = "Power lock", unit = "%", default = 0.35, min = 0, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("gearing", "Differential", { id = "drivetrain.coastLock", label = "Coast lock", unit = "%", default = 0.15, min = 0, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("gearing", "Differential", { id = "drivetrain.maxBias", label = "Max torque bias", default = 3, min = 1, max = 10, step = 0.1, tier = "advanced" })
def("gearing", "AWD", { id = "drivetrain.awdFront", label = "Front torque share", unit = "%", default = 0.4, min = 0, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("gearing", "AWD", { id = "drivetrain.centerDiff", label = "Center diff", kind = "enum", options = DIFFS, labels = { "Open", "LSD", "Torsen", "Clutch LSD", "Locked", "Welded" }, default = "LOCKED", tier = "advanced" })

-- Chassis
def("chassis", "Body", { id = "chassis.mass", label = "Mass", unit = "kg", default = 1500, min = 300, max = 6000, step = 10 })
def("chassis", "Body", { id = "chassis.weightFront", label = "Front weight", unit = "%", default = 0.68, min = 0.3, max = 0.8, step = 0.01, display = "percent", hint = "Where the centre of mass sits between the axles." })
def("chassis", "Body", { id = "chassis.cgHeight", label = "CG height", unit = "m", default = 0.75, min = 0.2, max = 1.6, step = 0.01, tier = "advanced" })
def("chassis", "Body", { id = "chassis.driverSide", label = "Driver seat", kind = "enum", options = { "Right", "Left" }, default = "Right", tier = "advanced" })
def("chassis", "Body", { id = "chassis.bodyCollision", label = "Body collision", kind = "bool", default = true, tier = "advanced" })
def("chassis", "Steering", { id = "steering.lock", label = "Steering lock", unit = "°", default = 44, min = 10, max = 70, step = 1 })
def("chassis", "Steering", { id = "steering.speed", label = "Steering speed", unit = "/s", default = 1.5, min = 0.2, max = 8, step = 0.05 })
def("chassis", "Steering", { id = "steering.returnSpeed", label = "Return speed", unit = "/s", default = 0.7, min = 0.1, max = 8, step = 0.05, tier = "advanced" })
def("chassis", "Steering", { id = "steering.falloff", label = "Speed sensitivity", unit = "km/h", default = 110, min = 20, max = 500, step = 5, tier = "advanced", hint = "Speed where available lock has halved." })
def("chassis", "Steering", { id = "steering.minScale", label = "Min. lock at speed", unit = "%", default = 0.2, min = 0.05, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("chassis", "Wheels", { id = "wheels.inertia", label = "Wheel inertia", unit = "kg·m²", min = 0.05, max = 5, step = 0.01, tier = "advanced", auto = function(ctx)
	local g = ctx.geo
	local r = (g.radiusFront + g.radiusRear) * 0.5 * Spec.STUD
	return math.floor(Spec.INERTIA_PER_R2 * r * r * 1000 + 0.5) / 1000
end })

-- Suspension
def("suspension", "Springs", { id = "suspension.freqFront", label = "Front ride freq.", unit = "Hz", default = 1.52, min = 0.5, max = 5, step = 0.05, hint = "Springs are rated from mass so the car keeps this frequency." })
def("suspension", "Springs", { id = "suspension.freqRear", label = "Rear ride freq.", unit = "Hz", default = 2.15, min = 0.5, max = 5, step = 0.05 })
def("suspension", "Springs", { id = "suspension.rideHeight", label = "Ride height", unit = "cm", default = 0, min = -15, max = 15, step = 0.5 })
def("suspension", "Dampers", { id = "suspension.dampFront", label = "Front damping", default = 0.352, min = 0.05, max = 1.5, step = 0.005, hint = "Damping ratio. 0.3 soft, 0.7 firm." })
def("suspension", "Dampers", { id = "suspension.dampRear", label = "Rear damping", default = 0.477, min = 0.05, max = 1.5, step = 0.005 })
def("suspension", "Travel", { id = "suspension.bump", label = "Bump travel", unit = "cm", min = 2, max = 60, step = 0.5, tier = "advanced", auto = function(ctx)
	return math.floor(ctx.geo.radiusFront * 0.35 * Spec.STUD * 1000 + 0.5) / 10
end })
def("suspension", "Travel", { id = "suspension.droop", label = "Droop travel", unit = "cm", min = 2, max = 60, step = 0.5, tier = "advanced", auto = function(ctx)
	return math.floor(ctx.geo.radiusFront * 0.40 * Spec.STUD * 1000 + 0.5) / 10
end })
def("suspension", "Travel", { id = "tires.sidewall", label = "Tire stiffness", unit = "×", default = 1, min = 0.4, max = 3, step = 0.05, tier = "advanced" })

-- Tires
def("tires", "Grip", { id = "tires.gripFront", label = "Front grip", default = 1.6, min = 0.3, max = 3, step = 0.01 })
def("tires", "Grip", { id = "tires.gripRear", label = "Rear grip", default = 1.35, min = 0.3, max = 3, step = 0.01 })
def("tires", "Grip", { id = "tires.traction", label = "Traction", default = 1, min = 0.3, max = 3, step = 0.01, hint = "Longitudinal grip for accelerating and braking." })
def("tires", "Response", { id = "tires.stiffFront", label = "Front stiffness", default = 1.6, min = 0.3, max = 4, step = 0.01, tier = "advanced", hint = "How quickly lateral force builds with slip angle." })
def("tires", "Response", { id = "tires.stiffRear", label = "Rear stiffness", default = 1.35, min = 0.3, max = 4, step = 0.01, tier = "advanced" })
def("tires", "Response", { id = "tires.relaxLong", label = "Long. relaxation", unit = "m", default = 0.35, min = 0.02, max = 2, step = 0.01, tier = "advanced" })
def("tires", "Response", { id = "tires.relaxLat", label = "Lat. relaxation", unit = "m", default = 0.4, min = 0.02, max = 2, step = 0.01, tier = "advanced" })
def("tires", "Realism", { id = "tires.combinedSlip", label = "Combined slip", unit = "%", default = 0.35, min = 0, max = 1, step = 0.01, display = "percent", hint = "0% = classic friction circle. 100% = spinning or locked tires lose most cornering grip." })
def("tires", "Realism", { id = "tires.lateralTransfer", label = "Lateral load transfer", unit = "%", default = 0.5, min = 0, max = 1, step = 0.01, display = "percent", hint = "Unloads the inside tires in corners." })
def("tires", "Realism", { id = "tires.rollBalance", label = "Roll balance (front)", unit = "%", default = 0.5, min = 0.1, max = 0.9, step = 0.01, display = "percent", tier = "advanced" })
def("tires", "Realism", { id = "tires.weightGrip", label = "Weight-based grip", unit = "%", default = 0, min = 0, max = 1, step = 0.01, display = "percent", tier = "advanced", hint = "Blend static tire load toward the real front/rear weight split." })
def("tires", "Realism", { id = "tires.loadSensLat", label = "Lat. load sensitivity", default = 0.22, min = 0, max = 0.6, step = 0.01, tier = "advanced" })
def("tires", "Realism", { id = "tires.loadSensLong", label = "Long. load sensitivity", default = 0.15, min = 0, max = 0.6, step = 0.01, tier = "advanced" })

-- Brakes
def("brakes", "Brakes", { id = "brakes.strength", label = "Brake strength", unit = "g", default = 1.32, min = 0.2, max = 3, step = 0.01, hint = "Peak brake force as deceleration. Torques follow mass and wheel size." })
def("brakes", "Brakes", { id = "brakes.bias", label = "Front bias", unit = "%", default = 0.605, min = 0.2, max = 0.9, step = 0.005, display = "percent" })
def("brakes", "Brakes", { id = "brakes.handbrake", label = "Handbrake", unit = "g", default = 1.11, min = 0, max = 3, step = 0.01 })

-- Aero
def("aero", "Drag", { id = "aero.cd", label = "Drag coefficient", default = 0.30, min = 0.05, max = 1.5, step = 0.01 })
def("aero", "Drag", { id = "aero.area", label = "Frontal area", unit = "m²", default = 1.95, min = 0.5, max = 8, step = 0.05 })
def("aero", "Downforce", { id = "aero.downforceFront", label = "Front downforce", unit = "ClA", default = 0, min = 0, max = 5, step = 0.05, hint = "Lift coefficient × area. 1.0 ≈ 900 N at 140 km/h." })
def("aero", "Downforce", { id = "aero.downforceRear", label = "Rear downforce", unit = "ClA", default = 0, min = 0, max = 5, step = 0.05 })
def("aero", "Rolling", { id = "aero.rollingResistance", label = "Rolling resistance", default = 0.011, min = 0, max = 0.1, step = 0.001, tier = "advanced" })
def("aero", "Rolling", { id = "aero.rho", label = "Air density", unit = "kg/m³", default = 1.225, min = 0.3, max = 2, step = 0.005, tier = "advanced" })

-- Assists
def("assists", "Driver aids", { id = "assists.abs", label = "ABS", kind = "bool", default = false })
def("assists", "Driver aids", { id = "assists.tcs", label = "Traction control", kind = "bool", default = false })
def("assists", "Pedals", { id = "inputs.throttle", label = "Throttle response", unit = "s", default = 0.05, min = 0, max = 1, step = 0.01, tier = "advanced" })
def("assists", "Pedals", { id = "inputs.brake", label = "Brake response", unit = "s", default = 0.12, min = 0, max = 1, step = 0.01, tier = "advanced" })
def("assists", "Pedals", { id = "inputs.clutch", label = "Clutch response", unit = "s", default = 0.04, min = 0.01, max = 1, step = 0.01, tier = "advanced" })
def("assists", "Debug", { id = "debug.enabled", label = "Debug attributes", kind = "bool", default = false, tier = "advanced" })

-- Camera
def("camera", "Camera", { id = "camera.mode", label = "Mode", kind = "enum", options = { "Chase", "Simple", "Racing" }, default = "Chase", hint = "X cycles modes while driving." })
def("camera", "Camera", { id = "camera.distance", label = "Chase distance", unit = "st", default = 20, min = 6, max = 60, step = 0.5 })
def("camera", "Camera", { id = "camera.height", label = "Chase height", unit = "st", default = 2.6, min = 0, max = 12, step = 0.1 })
def("camera", "Camera", { id = "camera.fov", label = "Base FOV", unit = "°", default = 68, min = 40, max = 110, step = 1 })
def("camera", "Camera", { id = "camera.speedFov", label = "Speed FOV", unit = "°", default = 10, min = 0, max = 40, step = 1, tier = "advanced" })

-- Sound
def("sound", "Engine", { id = "sound.packOn", label = "On-throttle loops", kind = "pack", default = "auto" })
def("sound", "Engine", { id = "sound.packOff", label = "Off-throttle loops", kind = "pack", default = "auto" })
def("sound", "Engine", { id = "sound.volume", label = "Engine volume", unit = "%", default = 1, min = 0, max = 2, step = 0.01, display = "percent" })
def("sound", "Engine", { id = "sound.offVolume", label = "Off-throttle level", unit = "%", default = 0.775, min = 0, max = 2, step = 0.01, display = "percent", tier = "advanced" })
def("sound", "Engine", { id = "sound.layerTilt", label = "High-rpm emphasis", unit = "%", default = 0.25, min = 0, max = 1, step = 0.01, display = "percent", tier = "advanced" })
def("sound", "Engine", { id = "sound.idle", label = "Idle loop", kind = "sound", default = "rbxassetid://136307885787958" })
def("sound", "Effects", { id = "sound.squeal", label = "Tire squeal", kind = "sound", default = "skid_long_noise.wav" })
def("sound", "Effects", { id = "sound.skid", label = "Tire skid (loose)", kind = "sound", default = "skid_long_hq.wav", tier = "advanced" })
def("sound", "Effects", { id = "sound.wind", label = "Wind", kind = "sound", default = "wind.wav" })
def("sound", "Effects", { id = "sound.turbo", label = "Turbo spool", kind = "sound", default = "rbxassetid://0" })
def("sound", "Effects", { id = "sound.brakeSqueal", label = "Brake squeal", kind = "sound", default = "rbxassetid://115235942061332", tier = "advanced" })

------------------------------------------------------------------------------------------
-- Presets. Values are applied on top of the defaults.
------------------------------------------------------------------------------------------

Spec.presets = {
	{ name = "Factory", note = "The stock tune.", values = {} },
	{
		name = "Street",
		note = "Softer and more forgiving.",
		values = {
			["suspension.freqFront"] = 1.25, ["suspension.freqRear"] = 1.7,
			["suspension.dampFront"] = 0.3, ["suspension.dampRear"] = 0.36,
			["tires.gripFront"] = 1.45, ["tires.gripRear"] = 1.35,
			["brakes.strength"] = 1.1, ["assists.abs"] = true, ["assists.tcs"] = true,
			["steering.speed"] = 1.3, ["tires.combinedSlip"] = 0.25,
		},
	},
	{
		name = "Sport",
		note = "Firmer, sharper, limited-slip.",
		values = {
			["suspension.freqFront"] = 1.8, ["suspension.freqRear"] = 2.3,
			["suspension.dampFront"] = 0.45, ["suspension.dampRear"] = 0.5,
			["tires.gripFront"] = 1.7, ["tires.gripRear"] = 1.5,
			["drivetrain.diff"] = "LIMITED", ["brakes.strength"] = 1.45,
			["suspension.rideHeight"] = -2,
		},
	},
	{
		name = "Track",
		note = "Stiff, low, aero and lots of grip.",
		values = {
			["suspension.freqFront"] = 2.4, ["suspension.freqRear"] = 2.8,
			["suspension.dampFront"] = 0.55, ["suspension.dampRear"] = 0.6,
			["tires.gripFront"] = 1.85, ["tires.gripRear"] = 1.75,
			["tires.stiffFront"] = 1.9, ["tires.stiffRear"] = 1.8,
			["aero.downforceFront"] = 0.6, ["aero.downforceRear"] = 0.9,
			["drivetrain.diff"] = "CLUTCH_LSD", ["brakes.strength"] = 1.6,
			["chassis.cgHeight"] = 0.65, ["suspension.rideHeight"] = -4,
			["tires.combinedSlip"] = 0.5,
		},
	},
	{
		name = "Drift",
		note = "Welded diff, big lock, loose rear.",
		values = {
			["drivetrain.diff"] = "WELDED", ["steering.lock"] = 58, ["steering.speed"] = 2.4,
			["steering.returnSpeed"] = 1.6, ["steering.minScale"] = 0.45,
			["tires.gripFront"] = 1.7, ["tires.gripRear"] = 1.15, ["tires.traction"] = 0.95,
			["tires.combinedSlip"] = 0.75, ["suspension.freqFront"] = 2.0, ["suspension.freqRear"] = 1.9,
			["chassis.weightFront"] = 0.55, ["engine.peakTorque"] = 420,
			["brakes.handbrake"] = 1.6,
		},
	},
}

function Spec.preset(name)
	for _, preset in ipairs(Spec.presets) do
		if preset.name == name then
			return preset
		end
	end
	return Spec.presets[1]
end

------------------------------------------------------------------------------------------
-- Build: parameters + geometry -> physics stats
------------------------------------------------------------------------------------------

local function curvePoints(get)
	if get("engine.curveMode") == "Custom" then
		local custom = get("engine.curve")
		if type(custom) == "table" and #custom >= 2 then
			return custom
		end
	end
	return Spec.shapedCurve(
		get("engine.peakTorque"),
		get("engine.peakRpm"),
		get("engine.plateau"),
		get("engine.idle"),
		get("engine.redline"),
		get("engine.lowEnd"),
		get("engine.topEnd")
	)
end
Spec.curvePoints = curvePoints

local function soundId(value)
	if type(value) ~= "string" or value == "" then
		return "rbxassetid://0"
	end
	return value
end

-- Spring/damper/tire rates in Roblox units for one axle.
local function axleRates(get, geo, front)
	local KG = Spec.KG_TO_RMU
	local g = Spec.DRIVE_GRAVITY
	local mass = get("chassis.mass") * KG
	local share = front and get("chassis.weightFront") or (1 - get("chassis.weightFront"))
	local corner = mass * share * 0.5
	local freq = get(front and "suspension.freqFront" or "suspension.freqRear")
	local zeta = get(front and "suspension.dampFront" or "suspension.dampRear")
	local cos = math.max(front and (geo.strutCosFront or 1) or (geo.strutCosRear or 1), 0.3)
	local radius = front and geo.radiusFront or geo.radiusRear
	local width = front and geo.widthFront or geo.widthRear
	local wheelMass = math.pi * radius * radius * width * Spec.WHEEL_DENSITY

	local omega = 2 * math.pi * freq
	local wheelRate = corner * omega * omega
	local spring = wheelRate / (cos * cos)
	local damper = 2 * zeta * math.sqrt(wheelRate * corner) / (cos * cos)
	local staticForce = corner * g / cos

	local deflection = Spec.TIRE_DEFLECTION * radius / math.max(get("tires.sidewall"), 0.05)
	local tireRate = (corner + wheelMass) * g / deflection
	local tireDamper = 2 * Spec.TIRE_DAMPING * math.sqrt(tireRate * wheelMass)

	return {
		cornerMass = corner,
		wheelMass = wheelMass,
		spring = spring,
		damper = damper,
		staticForce = staticForce,
		strutCos = cos,
		tireRate = tireRate,
		tireDamper = tireDamper,
		tireDeflection = deflection,
		bump = get("suspension.bump") / 100 / Spec.STUD,
		droop = get("suspension.droop") / 100 / Spec.STUD,
	}
end

function Spec.build(get, geo)
	geo = geo or Spec.REFERENCE_GEOMETRY
	local STUD = Spec.STUD
	local rF = geo.radiusFront * STUD
	local rR = geo.radiusRear * STUD
	local layout = get("drivetrain.layout")
	local rDriven = layout == "FWD" and rF or layout == "RWD" and rR or (rF + rR) * 0.5
	local mass = get("chassis.mass")
	local weightKg = mass * Spec.G

	-- torque curve
	local points = curvePoints(get)
	local torqueCurve = {}
	for _, p in ipairs(points) do
		torqueCurve[math.floor(p.rpm + 0.5)] = p.torque
	end

	-- gears
	local gears = { [0] = 0, [-1] = -math.abs(get("gearbox.reverse")) }
	for i, ratio in ipairs(get("gearbox.gears")) do
		gears[i] = ratio
	end

	-- brakes from deceleration targets
	local brakeForce = get("brakes.strength") * weightKg
	local bias = get("brakes.bias")
	local handbrakeForce = get("brakes.handbrake") * weightKg

	-- sounds
	local sounds = clone(Spec.DEFAULT_SOUNDS)
	local packs = Spec.availablePacks and Spec.availablePacks() or {}
	local onPack = Spec.pickPack(packs, "on", get("sound.packOn"))
	local offPack = Spec.pickPack(packs, "off", get("sound.packOff")) or onPack
	local volume = get("sound.volume")
	local tilt = get("sound.layerTilt")
	local offLevel = get("sound.offVolume")
	sounds.engine.on = Spec.buildLayers(onPack, volume * (1 - tilt), volume)
	sounds.engine.off = Spec.buildLayers(offPack, volume * offLevel * (1 - tilt), volume * offLevel)
	sounds.engine.idle.id = soundId(get("sound.idle"))
	sounds.tires.squeal.id = soundId(get("sound.squeal"))
	sounds.tires.skidLoose.id = soundId(get("sound.skid"))
	sounds.body.wind.id = soundId(get("sound.wind"))
	sounds.turbo.spool.id = soundId(get("sound.turbo"))
	sounds.brakes.squeal.id = soundId(get("sound.brakeSqueal"))

	-- camera
	local camera = clone(Spec.DEFAULT_CAMERA)
	local modes = { Chase = 1, Simple = 2, Racing = 3 }
	camera.mode = modes[get("camera.mode")] or 1
	camera.advanced.distance = get("camera.distance")
	camera.advanced.height = get("camera.height")
	camera.advanced.fovBase = get("camera.fov")
	camera.advanced.fovSpeed = get("camera.speedFov")

	local front = axleRates(get, geo, true)
	local rear = axleRates(get, geo, false)

	return {
		wheelRadiusMeters = rDriven,
		wheelRadiusFront = rF,
		wheelRadiusRear = rR,
		massKg = mass,
		steerResponseTimeActive = get("steering.speed"),
		steerResponseTimeInactive = get("steering.returnSpeed"),
		throttleResponseTime = get("inputs.throttle"),
		brakeResponseTime = get("inputs.brake"),
		clutchResponseTime = get("inputs.clutch"),
		maxSteerDegrees = get("steering.lock"),
		steering = {
			falloffKmh = get("steering.falloff"),
			minScale = get("steering.minScale"),
		},
		frictconfig = {
			latGripFront = get("tires.gripFront"),
			latGripRear = get("tires.gripRear"),
			latStiffFront = get("tires.stiffFront"),
			latStiffRear = get("tires.stiffRear"),
			longGrip = get("tires.traction"),
		},
		tires = {
			combinedSlip = get("tires.combinedSlip"),
			lateralTransfer = get("tires.lateralTransfer"),
			rollBalance = get("tires.rollBalance"),
			weightGrip = get("tires.weightGrip"),
			relaxLong = get("tires.relaxLong"),
			relaxLat = get("tires.relaxLat"),
			loadSensLat = get("tires.loadSensLat"),
			loadSensLong = get("tires.loadSensLong"),
		},
		engine = {
			idleRPM = get("engine.idle"),
			redlineRPM = get("engine.redline"),
			inertia = get("engine.inertia"),
			torqueCurve = torqueCurve,
			friction = {
				static = get("engine.frictionStatic"),
				viscous = get("engine.frictionViscous"),
				pumpingLossCoefficient = get("engine.pumping"),
			},
			accessoryTorque = get("engine.accessory"),
			idleControl = {
				enabled = true,
				targetRPM = get("engine.idle"),
				authority = get("engine.idleAuthority"),
				stallRPM = get("engine.stallRpm"),
			},
			revLimiter = {
				rpm = get("engine.limiterRpm"),
				cut = get("engine.limiterCut"),
				hysteresis = get("engine.limiterHysteresis"),
			},
		},
		clutch = { maxTorque = get("clutch.maxTorque") },
		transmission = {
			type = layout,
			gears = gears,
			finalDrive = get("gearbox.finalDrive"),
			efficiency = get("gearbox.efficiency"),
			shiftTime = get("gearbox.shiftTime"),
			differential = {
				type = get("drivetrain.diff"),
				preload = get("drivetrain.preload"),
				powerLock = get("drivetrain.powerLock"),
				coastLock = get("drivetrain.coastLock"),
				maxBias = get("drivetrain.maxBias"),
			},
			awd = {
				frontBias = get("drivetrain.awdFront"),
				rearBias = 1 - get("drivetrain.awdFront"),
				centerDiff = get("drivetrain.centerDiff"),
			},
			gearbox = get("gearbox.mode"),
		},
		sounds = sounds,
		brakes = {
			maxTorqueFront = brakeForce * bias * 0.5 * rF,
			maxTorqueRear = brakeForce * (1 - bias) * 0.5 * rR,
			handbrakeTorque = handbrakeForce * 0.5 * rR,
		},
		assists = {
			abs = get("assists.abs"),
			tcs = get("assists.tcs"),
		},
		wheelInertia = get("wheels.inertia"),
		aero = {
			rho = get("aero.rho"),
			Cd = get("aero.cd"),
			area = get("aero.area"),
			rollingResistance = get("aero.rollingResistance"),
			downforceFront = get("aero.downforceFront"),
			downforceRear = get("aero.downforceRear"),
		},
		camera = camera,
		debug = { enabled = get("debug.enabled") },
		cgHeightMeters = get("chassis.cgHeight"),
		wheelbaseMeters = geo.wheelbase * STUD,
		trackFrontMeters = geo.trackFront * STUD,
		trackRearMeters = geo.trackRear * STUD,
		weightFront = get("chassis.weightFront"),
		chassis = {
			driverSide = get("chassis.driverSide"),
			bodyCollision = get("chassis.bodyCollision"),
			rideHeight = get("suspension.rideHeight") / 100 / STUD,
		},
		suspension = { front = front, rear = rear },
	}
end

------------------------------------------------------------------------------------------
-- Read-outs for the tuning UI
------------------------------------------------------------------------------------------

local function torqueAt(points, rpm)
	if rpm <= points[1].rpm then
		return points[1].torque
	end
	for i = 1, #points - 1 do
		local a, b = points[i], points[i + 1]
		if rpm <= b.rpm then
			return a.torque + (b.torque - a.torque) * (rpm - a.rpm) / math.max(b.rpm - a.rpm, 1)
		end
	end
	return points[#points].torque
end
Spec.torqueAt = torqueAt

function Spec.readouts(get, stats)
	local points = curvePoints(get)
	local idle, redline = get("engine.idle"), get("engine.redline")
	local peakPower, peakPowerRpm, peakTorque, peakTorqueRpm = 0, idle, 0, idle
	for rpm = idle, redline, 50 do
		local t = torqueAt(points, rpm)
		local p = t * rpm / 9549
		if p > peakPower then
			peakPower, peakPowerRpm = p, rpm
		end
		if t > peakTorque then
			peakTorque, peakTorqueRpm = t, rpm
		end
	end

	local mass = get("chassis.mass")
	local r = stats.wheelRadiusMeters
	local fd = stats.transmission.finalDrive
	local eff = stats.transmission.efficiency
	local gearSpeeds = {}
	for i, ratio in ipairs(get("gearbox.gears")) do
		local omega = redline * math.pi / 30 / (ratio * fd)
		gearSpeeds[i] = omega * r * 3.6
	end

	-- top speed: highest speed at which the best gear still out-pulls drag + rolling
	local aero = stats.aero
	local topSpeed = 0
	for v = 1, 140, 0.5 do
		local resist = 0.5 * aero.rho * aero.Cd * aero.area * v * v + aero.rollingResistance * mass * Spec.G
		local best = 0
		for _, ratio in ipairs(get("gearbox.gears")) do
			local rpm = v / r * ratio * fd * 30 / math.pi
			if rpm >= idle and rpm <= redline then
				best = math.max(best, torqueAt(points, rpm) * ratio * fd * eff / r)
			end
		end
		if best >= resist then
			topSpeed = v
		elseif topSpeed > 0 and v > topSpeed + 5 then
			break
		end
	end

	local toNmm = 1 / Spec.N_TO_FORCE / Spec.STUD / 1000
	local susp = stats.suspension
	return {
		peakPowerKw = peakPower,
		peakPowerHp = peakPower * 1.341,
		peakPowerRpm = peakPowerRpm,
		peakTorque = peakTorque,
		peakTorqueRpm = peakTorqueRpm,
		mass = mass,
		powerToWeight = peakPower * 1.341 / (mass / 1000),
		gearSpeeds = gearSpeeds,
		topSpeedKmh = topSpeed * 3.6,
		springFront = susp.front.spring * toNmm,
		springRear = susp.rear.spring * toNmm,
		cornerFront = mass * get("chassis.weightFront") * 0.5,
		cornerRear = mass * (1 - get("chassis.weightFront")) * 0.5,
		brakeFront = stats.brakes.maxTorqueFront,
		brakeRear = stats.brakes.maxTorqueRear,
		points = points,
	}
end

return Spec
