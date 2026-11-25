/* The twelve complaint categories citizens choose from, in the order KAVACH shows them, and the one the
   citizen picked. The pick is remembered for the whole reporting process (home page -> sign in -> form). */

export const CIVIC = [
  { id: "garbage", name: "Garbage collection", icon: "trash", blurb: "Overflowing bins, garbage piles on the street and missed collections.",
    options: ["Overflowing bin", "Garbage pile on the street", "Garbage not collected"] },
  { id: "road_damage", name: "Road damage and potholes", icon: "road", blurb: "Potholes, cracked or sunken roads and broken road edges that put people at risk.",
    options: ["Pothole", "Cracked or sunken road", "Broken road edge or footpath"] },
  { id: "drainage", name: "Drainage problems", icon: "drain", blurb: "Blocked drains, overflowing sewers and water that will not clear after rain.",
    options: ["Blocked drain", "Sewage overflow", "Waterlogging"] },
  { id: "water_leakage", name: "Water leakage", icon: "droplet", blurb: "Leaking or burst pipes and water running onto the road.",
    options: ["Burst pipe", "Leaking tap or hydrant", "Dirty or no water supply"] },
  { id: "streetlight", name: "Streetlight problems", icon: "bulb", blurb: "Lights that are off, flickering, broken or left on in the day.",
    options: ["Light not working", "Flickering light", "Damaged pole or wires"] },
  { id: "public_toilet", name: "Public toilet maintenance", icon: "toilet", blurb: "Dirty or damaged public toilets, no water or no light.",
    options: ["Needs cleaning", "No water or light", "Broken door or fittings"] },
  { id: "sanitation", name: "Sanitation", icon: "broom", blurb: "Unswept streets, dirty public spaces and general cleanliness.",
    options: ["Street not swept", "Dirty public space", "Dead animal"] },
  { id: "waste_disposal", name: "Waste disposal", icon: "recycle", blurb: "Waste dumped in the open, burning of waste and illegal dumping.",
    options: ["Illegal dumping", "Burning waste", "Construction debris"] },
  { id: "infrastructure", name: "Public infrastructure", icon: "bench", blurb: "Damaged benches, bus stops, bridges, footpaths, parks and other public property.",
    options: ["Damaged bus stop or bench", "Broken footpath or railing", "Park or playground damage"] },
  { id: "highway", name: "Highway-related problems", icon: "highway", blurb: "Problems on state or national highways: damaged lanes, signs, dividers and lights.",
    options: ["Damaged highway lane", "Missing sign or divider", "Highway light not working"] },
  { id: "safety_hazard", name: "Public safety", icon: "alert", blurb: "Open manholes, fallen trees, exposed wires and other hazards that can hurt someone.",
    options: ["Open manhole", "Fallen tree or pole", "Exposed wires"] },
  { id: "other", name: "Other civic issues", icon: "dots", blurb: "Anything else in public space that needs the authorities' attention.",
    options: ["Describe the problem in your own words"] },
];

export const infoOf = (id) => CIVIC.find((c) => c.id === id) || null;

const KEY = "kavach.category";
export const selectedCategory = () => { try { return sessionStorage.getItem(KEY); } catch { return null; } };
export const selectCategory = (id) => { try { id ? sessionStorage.setItem(KEY, id) : sessionStorage.removeItem(KEY); } catch { /* private mode: not remembered */ } };
