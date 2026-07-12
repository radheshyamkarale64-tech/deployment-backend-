import os
import uuid
from datetime import date, datetime
from typing import List, Optional
from urllib.parse import quote_plus, unquote
import certifi
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
import bcrypt
from jose import JWTError, jwt
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv

# Load local environment variables from .env file
load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# App Setup
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="STEMQuest Gamified Learning Platform API",
    description=(
        "Complete backend API for STEMQuest — a gamified STEM learning platform "
        "designed for rural school students in India."
    ),
    version="3.0.0",
)

# ─────────────────────────────────────────────────────────────────────────────
# CORS Configuration
# ─────────────────────────────────────────────────────────────────────────────
FRONTEND_URL = os.getenv("FRONTEND_URL", "")

allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",   # vite preview
    "http://localhost:3000",   # alternative dev port
    "https://deployment-frontend-eight.vercel.app", # Netlify live app
    "https://deployment-frontend-eight.vercel.app" # Current Netlify live app
]

if FRONTEND_URL:
    allowed_origins.append(FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|https?://[a-zA-Z0-9-]+\.netlify\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Database Connectivity (MongoDB Atlas)
# ─────────────────────────────────────────────────────────────────────────────
def safe_mongo_uri(uri: str) -> str:
    if not uri.startswith("mongodb://") and not uri.startswith("mongodb+srv://"):
        return uri
    scheme = "mongodb+srv://" if uri.startswith("mongodb+srv://") else "mongodb://"
    rest = uri[len(scheme):]
    if "@" not in rest:
        return uri
    parts = rest.rsplit("@", 1)
    creds_part, host_part = parts[0], parts[1]
    if ":" not in creds_part:
        username = quote_plus(unquote(creds_part))
        return f"{scheme}{username}@{host_part}"
    username, password = creds_part.split(":", 1)
    escaped_user = quote_plus(unquote(username))
    escaped_pass = quote_plus(unquote(password))
    return f"{scheme}{escaped_user}:{escaped_pass}@{host_part}"

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_URI_SAFE = safe_mongo_uri(MONGO_URI)
client = AsyncIOMotorClient(MONGO_URI_SAFE, tlsCAFile=certifi.where())
db = client.get_database("stemquest")

@app.on_event("startup")
async def startup_db_client():
    try:
        # Ping the server to check connectivity
        await client.admin.command('ping')
        print("Connected successfully to MongoDB Atlas!")
        # Ensure indexes are set
        await db.users.create_index("username", unique=True)
        await db.users.create_index("user_id", unique=True)
    except Exception as e:
        print(f"CRITICAL: Failed to connect to MongoDB: {e}")
        print("Please check your MONGO_URI in the environment variables or .env file.")

# ─────────────────────────────────────────────────────────────────────────────
# Authentication Configuration
# ─────────────────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_stemquest_key_123_abc")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 1440  # 1 day (ideal for school environments)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

# ─────────────────────────────────────────────────────────────────────────────
# Core STEMQuest Game Configuration Data
# ─────────────────────────────────────────────────────────────────────────────
ALL_BADGES = {
    "explorer":    {"icon": "🧭", "name": "Explorer",    "desc": "Complete your first quest",          "required_points": 1},
    "scientist":   {"icon": "🧬", "name": "Scientist",   "desc": "Complete the Gravity Lab",           "required_points": 20},
    "coder":       {"icon": "🤖", "name": "Coder",       "desc": "Successfully code the robot",        "required_points": 25},
    "innovator":   {"icon": "🛠️", "name": "Innovator",   "desc": "Complete an Engineering challenge",  "required_points": 30},
    "math_wizard": {"icon": "📐", "name": "Math Wizard", "desc": "Complete the full Algebra quiz",     "required_points": 45},
    "challenger":  {"icon": "⚡", "name": "Challenger",  "desc": "Finish the daily challenge",         "required_points": 50},
    "rising_star": {"icon": "🌟", "name": "Rising Star", "desc": "Reach Level 2",                      "required_points": 100},
    "champion":    {"icon": "🏆", "name": "Champion",    "desc": "Reach Level 5",                      "required_points": 500},
}

MATH_QUESTIONS = [
    {"id": 1, "question": "Solve for x: x + 4 = 10",   "options": ["4", "6", "10", "14"],  "answer": "6",  "points": 15},
    {"id": 2, "question": "Solve for x: 2x - 3 = 7",   "options": ["2", "5", "8", "10"],   "answer": "5",  "points": 15},
    {"id": 3, "question": "Solve for x: 3x + 6 = 15",  "options": ["3", "5", "9", "21"],   "answer": "3",  "points": 15},
    {"id": 4, "question": "Solve for x: x/2 + 1 = 5",  "options": ["6", "8", "10", "12"],  "answer": "8",  "points": 20},
    {"id": 5, "question": "Solve for x: 5x - 10 = 20", "options": ["2", "4", "6", "8"],    "answer": "6",  "points": 20},
]

PLANET_DATA = {
    "Earth":   {"gravity": 9.8,  "emoji": "🌍", "fact": "Earth's gravity keeps the Moon in orbit!"},
    "Moon":    {"gravity": 1.6,  "emoji": "🌕", "fact": "On the Moon you can jump 6x higher than on Earth!"},
    "Jupiter": {"gravity": 24.8, "emoji": "🪐", "fact": "Jupiter's gravity is so strong it protects Earth from asteroids!"},
    "Mars":    {"gravity": 3.7,  "emoji": "🔴", "fact": "On Mars, you would weigh about 38% of your Earth weight!"},
}

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: str = Field(..., min_length=4)
    name: str = Field(..., min_length=1)
    school: str = Field(..., min_length=1)

class LoginRequest(BaseModel):
    username: str
    password: str

class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    school: Optional[str] = None

class TutorRequest(BaseModel):
    question: str

class AnswerRequest(BaseModel):
    question_id: int
    answer: str

# ─────────────────────────────────────────────────────────────────────────────
# Security Helper Functions
# ─────────────────────────────────────────────────────────────────────────────
def verify_password(plain_password, hashed_password):
    try:
        return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception:
        return False

def get_password_hash(password):
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def create_access_token(username: str):
    to_encode = {"sub": username}
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user = await db.users.find_one({"username": username})
    if user is None:
        raise credentials_exception
    return user

# ─────────────────────────────────────────────────────────────────────────────
# Game Engine Helper Functions
# ─────────────────────────────────────────────────────────────────────────────
def _default_user_doc(username: str, name: str, school: str, hashed_pass: str) -> dict:
    return {
        "user_id": str(uuid.uuid4()),
        "username": username,
        "password_hash": hashed_pass,
        "name": name,
        "school": school,
        "points": 0,
        "level": 1,
        "streak": 1,
        "last_login": str(date.today()),
        "badges_earned": [],
        "quests_completed": 0,
        "daily_challenge_done": False,
        "daily_challenge_date": "",
        "created_at": datetime.utcnow().isoformat(),
    }

def _update_login_streak(user: dict) -> dict:
    today_str = str(date.today())
    last_login_str = user.get("last_login")
    
    if last_login_str == today_str:
        return user
        
    try:
        last_login_date = datetime.strptime(last_login_str, "%Y-%m-%d").date()
        today_date = date.today()
        delta = today_date - last_login_date
        
        if delta.days == 1:
            user["streak"] = user.get("streak", 0) + 1
        elif delta.days > 1:
            user["streak"] = 1
    except Exception:
        user["streak"] = 1
        
    user["last_login"] = today_str
    return user

def _check_and_award_badges(user: dict) -> list:
    newly_earned = []
    badges_earned = user.get("badges_earned", [])
    for badge_id, badge in ALL_BADGES.items():
        if badge_id not in badges_earned:
            if user["points"] >= badge["required_points"]:
                badges_earned.append(badge_id)
                newly_earned.append(badge_id)
    user["badges_earned"] = badges_earned
    return newly_earned

def _level_up(user: dict) -> None:
    new_level = 1 + user["points"] // 100
    user["level"] = new_level

def _build_user_response(user: dict) -> dict:
    badges = []
    badges_earned = user.get("badges_earned", [])
    for badge_id, badge_data in ALL_BADGES.items():
        badges.append({
            "id": badge_id,
            "icon": badge_data["icon"],
            "name": badge_data["name"],
            "desc": badge_data["desc"],
            "earned": badge_id in badges_earned,
        })

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "name": user["name"],
        "school": user["school"],
        "points": user["points"],
        "level": user["level"],
        "streak": user["streak"],
        "quests_completed": user["quests_completed"],
        "daily_challenge_done": user["daily_challenge_done"],
        "badges": badges,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Routes — System
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/", tags=["System"])
def read_root():
    return {
        "message": "Welcome to the STEMQuest API v3 (MongoDB & JWT Auth Integration)! 🚀",
        "status": "running",
        "version": "3.0.0",
        "docs": "/docs",
    }

@app.get("/health", tags=["System"])
async def health_check():
    try:
        await client.admin.command('ping')
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return {"status": "ok", "database": db_status, "version": "3.0.0"}

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Authentication
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/api/auth/register", tags=["Auth"])
async def register_user(body: RegisterRequest):
    """Register a new student account. Assures data persistence in MongoDB Atlas."""
    existing_user = await db.users.find_one({"username": body.username})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken. Try adding a number or initials!"
        )
    
    hashed_pass = get_password_hash(body.password)
    user_doc = _default_user_doc(body.username, body.name, body.school, hashed_pass)
    
    try:
        await db.users.insert_one(user_doc)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database write failure: {e}"
        )
        
    token = create_access_token(user_doc["username"])
    return {
        "token": token,
        "user": _build_user_response(user_doc)
    }

@app.post("/api/auth/login", tags=["Auth"])
async def login_user(body: LoginRequest):
    """Authenticate and login a student, returning their stats and JWT session token."""
    user = await db.users.find_one({"username": body.username})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password. Check spelling and try again!"
        )
        
    user = _update_login_streak(user)
    await db.users.update_one(
        {"user_id": user["user_id"]},
        {"$set": {"last_login": user["last_login"], "streak": user["streak"]}}
    )
    
    token = create_access_token(user["username"])
    return {
        "token": token,
        "user": _build_user_response(user)
    }

# ─────────────────────────────────────────────────────────────────────────────
# Routes — User Stats (Protected)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/user/me", tags=["User"])
async def get_user_stats(current_user: dict = Depends(get_current_user)):
    """Fetch current authenticated student's stats."""
    updated_user = _update_login_streak(current_user)
    if updated_user["last_login"] != current_user["last_login"] or updated_user["streak"] != current_user["streak"]:
        await db.users.update_one(
            {"user_id": current_user["user_id"]},
            {"$set": {"last_login": updated_user["last_login"], "streak": updated_user["streak"]}}
        )
    return _build_user_response(updated_user)

@app.post("/api/user/me/points", tags=["User"])
async def add_points(points: int, current_user: dict = Depends(get_current_user)):
    """Award XP points for completing games or lessons."""
    if points < 0:
        raise HTTPException(status_code=400, detail="Points must be a positive number")
        
    current_user["points"] += points
    current_user["quests_completed"] += 1
    
    _level_up(current_user)
    new_badges = _check_and_award_badges(current_user)
    
    await db.users.update_one(
        {"user_id": current_user["user_id"]},
        {
            "$set": {
                "points": current_user["points"],
                "level": current_user["level"],
                "quests_completed": current_user["quests_completed"],
                "badges_earned": current_user["badges_earned"]
            }
        }
    )
    
    response = _build_user_response(current_user)
    response["new_badges"] = new_badges
    return response

@app.post("/api/user/me/daily-challenge", tags=["User"])
async def complete_daily_challenge(current_user: dict = Depends(get_current_user)):
    """Complete the daily challenge and earn 50 XP (restricted to once a day)."""
    today = str(date.today())
    
    if current_user.get("daily_challenge_done") and current_user.get("daily_challenge_date") == today:
        return {
            "message": "Daily challenge already completed today! Come back tomorrow.",
            "already_done": True,
            **_build_user_response(current_user),
        }
        
    current_user["points"] += 50
    current_user["daily_challenge_done"] = True
    current_user["daily_challenge_date"] = today
    current_user["quests_completed"] += 1
    
    _level_up(current_user)
    new_badges = _check_and_award_badges(current_user)
    
    await db.users.update_one(
        {"user_id": current_user["user_id"]},
        {
            "$set": {
                "points": current_user["points"],
                "level": current_user["level"],
                "daily_challenge_done": True,
                "daily_challenge_date": today,
                "quests_completed": current_user["quests_completed"],
                "badges_earned": current_user["badges_earned"]
            }
        }
    )
    
    response = _build_user_response(current_user)
    response["new_badges"] = new_badges
    response["already_done"] = False
    response["message"] = "Daily challenge completed! +50 XP awarded!"
    return response

@app.post("/api/user/me/name", tags=["User"])
async def update_user_name(body: UpdateUserRequest, current_user: dict = Depends(get_current_user)):
    """Update user's screen display name and school."""
    update_data = {}
    if body.name is not None:
        update_data["name"] = body.name
        current_user["name"] = body.name
    if body.school is not None:
        update_data["school"] = body.school
        current_user["school"] = body.school
        
    if update_data:
        await db.users.update_one({"user_id": current_user["user_id"]}, {"$set": update_data})
        
    return _build_user_response(current_user)

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Leaderboard (Authenticated or Guest)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/leaderboard", tags=["Leaderboard"])
async def get_leaderboard(current_user: Optional[dict] = Depends(get_current_user)):
    """Fetch global leaderboard top 10 from MongoDB."""
    cursor = db.users.find({}, {"name": 1, "school": 1, "points": 1, "level": 1, "user_id": 1}).sort("points", -1).limit(10)
    top_users = await cursor.to_list(length=10)
    
    leaderboard = []
    for idx, u in enumerate(top_users):
        is_current = False
        if current_user and current_user.get("user_id") == u["user_id"]:
            is_current = True
            
        leaderboard.append({
            "rank": idx + 1,
            "name": u["name"],
            "school": u["school"],
            "points": u["points"],
            "level": u["level"],
            "is_current_user": is_current,
        })
        
    # If authenticated user isn't in top 10, fetch and append their actual rank
    if current_user and not any(entry["is_current_user"] for entry in leaderboard):
        user_rank = await db.users.count_documents({"points": {"$gt": current_user["points"]}}) + 1
        leaderboard.append({
            "rank": user_rank,
            "name": current_user["name"],
            "school": current_user["school"],
            "points": current_user["points"],
            "level": current_user["level"],
            "is_current_user": True,
        })
        
    total_players = await db.users.count_documents({})
    return {"leaderboard": leaderboard, "total_players": total_players}

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Platform Stats
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/stats", tags=["System"])
async def get_platform_stats():
    """Fetch live totals across all students from MongoDB Atlas."""
    total_students = await db.users.count_documents({})
    
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$quests_completed"}}}]
    cursor = db.users.aggregate(pipeline)
    agg_result = await cursor.to_list(length=1)
    total_quests = agg_result[0]["total"] if agg_result else 0
    
    schools = await db.users.distinct("school")
    total_schools = len([s for s in schools if s])
    
    return {
        "total_students": total_students,
        "total_quests_completed": total_quests,
        "total_schools": total_schools,
    }

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Math Quest
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/quests/math", tags=["Quests"])
def get_math_questions():
    """Fetch equations quiz questions."""
    return {
        "questions": MATH_QUESTIONS,
        "total": len(MATH_QUESTIONS),
        "subject": "Algebra",
        "description": "Solve algebra equations to earn XP points!",
    }

@app.post("/api/quests/math/answer", tags=["Quests"])
async def check_math_answer(body: AnswerRequest, current_user: Optional[dict] = Depends(get_current_user)):
    """Validate answers server-side."""
    question = next((q for q in MATH_QUESTIONS if q["id"] == body.question_id), None)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    is_correct = body.answer == question["answer"]
    points_earned = question["points"] if is_correct else 0

    result = {
        "correct": is_correct,
        "correct_answer": question["answer"],
        "points_earned": points_earned,
        "explanation": f"The answer is {question['answer']}"
    }

    if is_correct and current_user:
        current_user["points"] += points_earned
        current_user["quests_completed"] += 1
        _level_up(current_user)
        _check_and_award_badges(current_user)
        
        await db.users.update_one(
            {"user_id": current_user["user_id"]},
            {
                "$set": {
                    "points": current_user["points"],
                    "level": current_user["level"],
                    "quests_completed": current_user["quests_completed"],
                    "badges_earned": current_user["badges_earned"]
                }
            }
        )
        result["user"] = _build_user_response(current_user)

    return result

# ─────────────────────────────────────────────────────────────────────────────
# Routes — Science Quest
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/api/science/planets", tags=["Quests"])
def get_planet_data():
    """Fetch planet parameters for gravity drop lab."""
    return {
        "planets": [
            {
                "name": name,
                "gravity": data["gravity"],
                "emoji": data["emoji"],
                "fact": data["fact"],
            }
            for name, data in PLANET_DATA.items()
        ]
    }

# ─────────────────────────────────────────────────────────────────────────────
# Routes — AI Tutor
# ─────────────────────────────────────────────────────────────────────────────
TUTOR_RESPONSES = {
    "gravity": (
        "Gravity is an invisible pull! 🍎 Think of it like a magnet. "
        "Earth pulls everything towards its center — that's why when you throw a ball up, "
        "it always comes back down. Sir Isaac Newton discovered this when an apple fell on him! "
        "Formula: F = m × g (Force = Mass × Gravity)"
    ),
    "photosynthesis": (
        "Photosynthesis is how plants make their food! 🌿 "
        "Plants take sunlight + water (from soil) + CO₂ (from air) "
        "and convert them into glucose (sugar) + oxygen. "
        "It's like a tiny solar-powered kitchen inside every leaf! "
        "Formula: 6CO₂ + 6H₂O + light → C₆H₁₂O₆ + 6O₂"
    ),
    "algebra": (
        "Algebra is a treasure hunt with numbers! 🔍 "
        "Instead of just numbers, we use letters like 'x' or 'y' to represent unknown values. "
        "If x + 2 = 5, we subtract 2 from both sides → x = 3. "
        "The key rule: whatever you do to one side, do the same to the other!"
    ),
    "force": (
        "Force is a push or a pull! 💪 Newton's 3 famous laws: "
        "1️⃣ Objects stay still or keep moving unless a force acts on them. "
        "2️⃣ Force = Mass × Acceleration (F = ma). "
        "3️⃣ Every action has an equal and opposite reaction — rockets use this to fly!"
    ),
    "newton": (
        "Sir Isaac Newton (1643-1727) was one of the greatest scientists ever! 🍎 "
        "He discovered: Gravity (when an apple fell near him), "
        "the 3 Laws of Motion, and invented calculus (a type of advanced math). "
        "His book 'Principia Mathematica' changed science forever!"
    ),
    "coding": (
        "Coding is giving step-by-step instructions to a computer! 💻 "
        "Just like a recipe tells a cook what to do, code tells computers what to do. "
        "Popular languages: Python (science/AI), JavaScript (websites), Scratch (beginners). "
        "Start with Scratch or Python — both are free and fun!"
    ),
    "program": (
        "Programming means writing instructions a computer can understand! 🤖 "
        "Every app, website, and game you use was written by a programmer. "
        "You can start learning for free at code.org or scratch.mit.edu. "
        "Remember: computers do EXACTLY what you tell them — so be precise!"
    ),
    "cell": (
        "Cells are the building blocks of all living things! 🔬 "
        "Like LEGO bricks of life — your body has ~37 TRILLION cells! "
        "Plant cells have a rigid cell wall (like a box) and chloroplasts for photosynthesis. "
        "Animal cells are more flexible and have a nucleus (the brain of the cell)."
    ),
    "biology": (
        "Biology is the study of all living things! 🌱 "
        "From tiny bacteria to giant blue whales, biology covers it all. "
        "Key topics: cells, genetics (DNA), evolution, ecosystems, and the human body. "
        "Biology helps us understand medicine, farming, and protecting our environment!"
    ),
    "water": (
        "Water (H₂O) is essential for all life on Earth! 💧 "
        "It exists in 3 states: solid (ice), liquid (water), gas (steam). "
        "The water cycle: evaporation → condensation → precipitation (rain/snow) → back to rivers. "
        "70% of Earth's surface is water, but only 3% is freshwater — conserve it!"
    ),
    "math": (
        "Math is the language of the universe! ➕ "
        "It's everywhere: in music, nature (Fibonacci sequence in flowers!), buildings, and space. "
        "Don't be scared — start with what you know and build step by step. "
        "Tip: Practice daily for 15 minutes. Consistency beats marathon sessions!"
    ),
    "energy": (
        "Energy is the ability to do work! ⚡ "
        "Types: Kinetic (moving objects), Potential (stored), Thermal (heat), Solar (sun), Electrical. "
        "Law of Conservation: Energy cannot be created or destroyed, only transformed. "
        "Example: A falling ball converts potential energy → kinetic energy!"
    ),
    "atom": (
        "Atoms are the smallest building blocks of matter! ⚛️ "
        "Every object around you — your desk, air, water — is made of atoms. "
        "An atom has: protons & neutrons in the nucleus (center), and electrons orbiting around it. "
        "Atoms are so tiny that 1 million of them lined up = width of a human hair!"
    ),
    "planet": (
        "Our Solar System has 8 planets! 🪐 "
        "Mercury, Venus, Earth, Mars (rocky/inner) and Jupiter, Saturn, Uranus, Neptune (gas giants). "
        "Earth is special — it's the only planet with liquid water and life (that we know of!). "
        "Mnemonic: 'My Very Energetic Mother Just Served Us Noodles'"
    ),
    "light": (
        "Light is electromagnetic radiation that our eyes can detect! ☀️ "
        "Speed of light: 299,792,458 m/s — the fastest speed in the universe! "
        "White light splits into rainbow colors (VIBGYOR) through a prism. "
        "Light can behave as both a wave AND a particle (photon) — this is quantum physics!"
    ),
}

@app.post("/api/tutor", tags=["AI Tutor"])
def ask_tutor(payload: TutorRequest):
    """Get dynamic engaging explanations for student questions."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    question_lower = question.lower()
    response = None
    for keyword, answer in TUTOR_RESPONSES.items():
        if keyword in question_lower:
            response = answer
            break

    if not response:
        response = (
            f"Great STEM question! 🌟 You asked about: '{question}'. "
            f"Science and math are all around us in daily life. "
            f"Try asking about: gravity, photosynthesis, algebra, force, cells, energy, atoms, or coding. "
            f"I'll give you a super simple explanation! What class are you in?"
        )

    return {
        "response": response,
        "question": question,
        "suggested_topics": ["gravity", "photosynthesis", "algebra", "force", "coding", "cells", "energy"],
    }

@app.get("/api/tutor/topics", tags=["AI Tutor"])
def get_tutor_topics():
    return {
        "topics": list(TUTOR_RESPONSES.keys()),
        "total": len(TUTOR_RESPONSES),
        "hint": "Try asking about any of these topics!",
    }
