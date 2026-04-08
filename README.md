# 🚀 Atom - FastAPI Application Skeleton

**Atom** is a complete, ready-to-use skeleton for building FastAPI applications. Think of it as a starter template that includes all the common stuff you need when building a real-world API, so you can focus on your business logic instead of setting up the basics over and over again.

## 🎯 What is This?

This is a **production-ready foundation** for FastAPI apps. It's like getting a pre-built house foundation - all the essential infrastructure is already there, you just need to build your specific features on top of it.

### What's Included ✅
- **User management** (create, list, get users)
- **Database setup** with async SQLAlchemy
- **Background task processing** (for sending emails, etc.)
- **Proper logging** that actually helps you debug issues
- **Security middleware** (CORS, security headers)
- **Comprehensive testing** (unit tests + load testing)
- **Clean, organized code structure**
- **Configuration management** (development vs production settings)
- **Error handling** that returns proper error messages
- **Docker setup** (Dockerfile + docker-compose.yml with Redis)

### What's NOT Included ❌
- **Authentication** (JWT, OAuth, etc.) - every app needs different auth
- **Deployment scripts** - depends on where you deploy (AWS, Google Cloud, etc.)
- **Specific business logic** - that's what you'll build!

## 🏗️ Project Structure

Here's how the code is organized and why:

```
atom/
├── src/                          # All our application code
│   ├── core/                     # Foundation stuff (config, logging, events)
│   ├── middlewares/              # Security and request processing
│   ├── exceptions/               # Error handling
│   ├── db/                       # Database connection and setup
│   ├── modules/                  # Your app features (users, products, etc.)
│   │   └── users/               # Example: user management
│   │       ├── model.py         # Database table definition
│   │       ├── schemas.py       # Data validation (what comes in/goes out)
│   │       ├── service.py       # Business logic (the actual work)
│   │       └── router.py        # API endpoints (URLs)
│   ├── workers/                  # Background tasks
│   └── main.py                   # Starts everything up
├── tests/                        # All test code (mirrors src structure)
├── data/                         # Database files (SQLite)
├── requirements.txt              # Python packages we need
├── .env-example                  # Configuration template
├── .env.docker                   # Docker-specific environment
├── Dockerfile                    # Docker image definition
├── docker-compose.yml            # Multi-container setup
├── .dockerignore                 # Files to exclude from Docker builds
└── README.md                     # This file
```

## 🚀 Quick Start

Choose between running locally or using Docker:

### Option 1: Local Development

#### 1. Get the Code
```bash
# Clone or download this repository
cd atom
```

#### 2. Set Up Your Environment
```bash
# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install all dependencies
pip install -r requirements.txt
```

#### 3. Configure Your App
```bash
# Copy the example environment file
cp .env-example .env

# Edit .env with your settings (database URL, etc.)
# The defaults work fine for development
```

#### 4. Run the Application
```bash
python -m src.main
```

Your API will be running at `http://localhost:8000`

### Option 2: Docker Compose (Recommended)

#### 1. Get the Code
```bash
# Clone or download this repository
cd atom
```

#### 2. Run with Docker Compose
```bash
# Build and start all services (app + Redis)
docker-compose up --build

# Or run in detached mode (background)
docker-compose up --build -d

# View logs
docker-compose logs -f app

# Stop services
docker-compose down
```

Your API will be running at `http://localhost:8000`

**What's included in Docker setup:**
- FastAPI application container
- Redis container for background tasks
- Automatic service networking
- Health checks
- Volume persistence for SQLite database

### Try It Out
- **API Documentation**: `http://localhost:8000/docs` (interactive!)
- **Health Check**: `http://localhost:8000/health`
- **Create a User**: POST to `http://localhost:8000/api/v1/users`

## 🧪 Testing

We've included comprehensive testing so you can be confident your app works correctly.

### Run Unit Tests
```bash
# Run all tests
pytest

# Run tests with coverage (see how much code is tested)
pytest --cov=src --cov-report=html

# Run tests in parallel (faster)
pytest -n auto
```

### Run Load Tests
Load testing helps you see how your app performs under heavy traffic.

```bash
# First, make sure your app is running
python src/main.py

# In another terminal, run load tests
# Interactive mode (opens web interface)
locust -f tests/load_tests/locustfile.py --host=http://localhost:8000

# Headless mode (run from command line)
locust -f tests/load_tests/locustfile.py --host=http://localhost:8000 --headless -u 10 -r 2 -t 30s
```

## 🏛️ Architecture Explained (The Simple Version)

We've organized the code using **Clean Architecture** principles. Here's what that means in simple terms:

### Layers (from outside to inside)
1. **API Layer** (`router.py`) - Handles HTTP requests and responses
2. **Service Layer** (`service.py`) - Contains your business logic
3. **Database Layer** (`model.py`) - Talks to the database
4. **Core Layer** (`core/`) - Configuration and utilities

### Why This Structure?
- **Easy to test** - You can test business logic without HTTP requests
- **Easy to change** - Want to switch databases? Only change one layer
- **Easy to understand** - Each file has one clear purpose
- **Easy to scale** - Add new features by adding new modules

## 🔧 Core Components

### Configuration (`src/core/config.py`)
All your app settings in one place. Uses environment variables so you can have different settings for development vs production.

```python
# Example: database URL comes from environment
DATABASE_URL=sqlite+aiosqlite:///./atom.db  # Development
DATABASE_URL=postgresql+asyncpg://...       # Production
```

### Logging (`src/core/logging.py`)
Uses **Loguru** instead of Python's built-in logging because it's much easier to use and more powerful.

```python
from loguru import logger
logger.info("User created successfully")  # That's it!
```

### Database (`src/db/`)
- **Async SQLAlchemy** for database operations
- **Connection pooling** for better performance
- **Automatic table creation** on startup

### Middleware (`src/middlewares/`)
- **CORS** - Lets your frontend talk to your API
- **Security Headers** - Protects against common attacks
- **Error Handling** - Returns nice error messages instead of crashes

### Background Tasks (`src/workers/`)
Uses **Dramatiq** for tasks that should happen in the background (like sending emails).

```python
# Example: Send welcome email after user signup
send_welcome_email.send(user_id, user_email)  # Happens in background
```

## 📝 Adding New Features

Want to add a "products" module? Here's how:

### 1. Create the Module Structure
```bash
mkdir src/modules/products
touch src/modules/products/__init__.py
touch src/modules/products/model.py      # Database table
touch src/modules/products/schemas.py    # Data validation  
touch src/modules/products/service.py    # Business logic
touch src/modules/products/router.py     # API endpoints
```

### 2. Create the Database Model
```python
# src/modules/products/model.py
from sqlalchemy import Column, String, Float
from src.db.base import Base

class Product(Base):
    __tablename__ = "products"
    
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    description = Column(String)
```

### 3. Create Schemas for Data Validation
```python
# src/modules/products/schemas.py
from pydantic import BaseModel

class ProductCreate(BaseModel):
    name: str
    price: float
    description: str = None

class ProductResponse(ProductCreate):
    id: str
    created_at: datetime
```

### 4. Add Business Logic
```python
# src/modules/products/service.py
async def create_product(db: AsyncSession, product_data: ProductCreate):
    # Your business logic here
    pass
```

### 5. Create API Endpoints
```python
# src/modules/products/router.py
from fastapi import APIRouter

router = APIRouter(prefix="/products", tags=["products"])

@router.post("/")
async def create_product(...):
    # Your endpoint logic here
    pass
```

### 6. Register Your Router
```python
# src/main.py
from src.modules.products.router import router as products_router
app.include_router(products_router, prefix="/api/v1")
```

### 7. Add Tests
```python
# tests/modules/products/test_products_routes.py
async def test_create_product():
    # Your tests here
    pass
```

## 🌍 Environment Variables

Copy `.env-example` to `.env` and customize:

```bash
# App Settings
APP_NAME=Your App Name
ENVIRONMENT=development  # or production
DEBUG=true

# Database
DATABASE_URL=sqlite+aiosqlite:///./your_app.db

# Redis (for background tasks)
REDIS_HOST=localhost
REDIS_PORT=6379

# Security
CORS_ORIGINS=["http://localhost:3000", "http://localhost:8080"]
```

## 📈 Production Readiness

This skeleton is production-ready out of the box:

### Performance Features
- **Async everywhere** - Handles many requests simultaneously
- **Connection pooling** - Efficient database usage
- **Background tasks** - Don't make users wait for slow operations

### Security Features
- **CORS protection** - Controls which websites can call your API
- **Security headers** - Protects against common attacks
- **Input validation** - Prevents bad data from causing problems

### Monitoring & Debugging
- **Structured logging** - Easy to search and analyze logs
- **Health checks** - Monitor if your app is running properly
- **Error tracking** - Proper error messages for debugging

## 🤔 Frequently Asked Questions

### Why async instead of regular Python?

**Simple answer**: It's much faster for web APIs.

**Longer answer**: When someone makes a request to your API, there's often waiting involved (database queries, calling other APIs, etc.). With regular Python, your app sits there doing nothing during the wait. With async, your app can handle other requests while waiting. This means you can handle many more users with the same hardware.

```python
# Regular Python - blocks while waiting
def get_user(user_id):
    user = database.get(user_id)  # Waits here, can't do anything else
    return user

# Async Python - can handle other requests while waiting  
async def get_user(user_id):
    user = await database.get(user_id)  # Waits here, but handles other requests
    return user
```

### Why SQLAlchemy 2.x with async?

**Simple answer**: It's the best way to talk to databases in async Python.

**Longer answer**: SQLAlchemy is like a translator between Python and databases. Version 2.x has much better async support and cleaner syntax. The async part is important because database operations are slow, and async lets your app stay responsive while waiting for the database.

### Why this specific folder structure?

**Simple answer**: It keeps things organized and makes it easy to find code.

**Longer answer**: We separate code by what it does:
- `core/` - Basic app setup (config, logging)
- `modules/` - Your features (users, products, etc.)
- `db/` - Database connection stuff
- `middlewares/` - Security and request processing
- `workers/` - Background tasks

This way, when you need to find or change something, you know exactly where to look.

### Why Dramatiq for background tasks?

**Simple answer**: It's reliable and easy to use.

**Longer answer**: Some tasks shouldn't make users wait (sending emails, processing images, etc.). Dramatiq lets you run these tasks in the background. It's more reliable than other options because it uses Redis to remember tasks even if your app restarts.

```python
# Without background tasks - user waits
def signup_user(email):
    create_user_in_database(email)
    send_welcome_email(email)  # User waits for email to send
    return "User created"

# With background tasks - user doesn't wait
def signup_user(email):
    create_user_in_database(email)
    send_welcome_email.send(email)  # Happens in background
    return "User created"  # Returns immediately
```

### Why Loguru instead of Python's built-in logging?

**Simple answer**: It's much easier to use and more powerful.

**Longer answer**: Python's built-in logging requires lots of setup and configuration. Loguru works great with just one line:

```python
# Built-in logging - lots of setup
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info("Something happened")

# Loguru - just works
from loguru import logger
logger.info("Something happened")
```

Plus, Loguru automatically rotates log files, handles colors, and has better formatting.

### Why these specific middleware?

**Simple answer**: They protect your app and make it work better.

**Longer answer**:
- **CORS middleware** - Lets your frontend (React, Vue, etc.) talk to your API safely
- **Security headers middleware** - Adds headers that protect against common attacks

### Why separate schemas from models?

**Simple answer**: They do different jobs.

**Longer answer**:
- **Models** (`model.py`) - Describe your database tables
- **Schemas** (`schemas.py`) - Describe what data comes in and goes out of your API

This separation means you can change your API without changing your database, or vice versa.

```python
# Model - what's in the database
class User(Base):
    id = Column(String, primary_key=True)
    email = Column(String, unique=True)
    password_hash = Column(String)  # Never return this!
    
# Schema - what the API returns (no password!)
class UserResponse(BaseModel):
    id: str
    email: str
    # password_hash not included for security
```

### Why comprehensive testing?

**Simple answer**: So you know your app works correctly.

**Longer answer**: Tests automatically check that your app works as expected. When you make changes, tests catch problems before your users do. We include:
- **Integration tests** - Test that different parts work together  
- **Load tests** - Test how your app handles heavy traffic

### Why clean architecture?

**Simple answer**: It makes your code easier to work with as it grows.

**Longer answer**: Clean architecture separates different concerns into different layers:
- **Presentation** (routers) - Handles HTTP stuff
- **Business logic** (services) - Your actual app logic
- **Data** (models) - Database stuff

This means you can:
- Test business logic without HTTP requests
- Change databases without changing business logic
- Add new ways to access your app (REST API, GraphQL, etc.) without changing business logic

### Why not include authentication?

**Simple answer**: Every app needs different authentication.

**Longer answer**: Some apps need:
- Simple username/password
- OAuth (Google, GitHub login)
- JWT tokens
- API keys
- SAML for enterprise

Instead of picking one that might not fit your needs, we left it out so you can add exactly what you need.

### Why not include deployment scripts?

**Simple answer**: Every deployment is different.

**Longer answer**: You might deploy to:
- AWS (Elastic Beanstalk, ECS, Lambda)
- Google Cloud (Cloud Run, App Engine)
- Heroku
- Your own servers with Docker
- Kubernetes

Each has different requirements, so we focused on making the app deployment-ready rather than picking one deployment method.

---

## Resources
- https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- 

---

## 🎉 What's Next?

1. **Start building your features** - Add your own modules following the examples
2. **Add authentication** - Choose the auth method that fits your needs
3. **Set up deployment** - Pick your hosting platform and deploy
4. **Monitor and scale** - Use the logging and health checks to monitor your app

## 🤝 Contributing

Found something that could be improved? Have an idea for a feature that would help many FastAPI projects? Feel free to contribute! This skeleton is meant to evolve with common needs.

---

**Happy coding! 🚀**