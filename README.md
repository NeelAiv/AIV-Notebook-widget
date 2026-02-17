# InsightEdge AI Notebook

InsightEdge AI Notebook is an interactive, AI-powered workspace designed for data exploration, SQL execution, and document analysis. It combines the flexibility of notebooks with a powerful AI assistant to streamline your research and data workflows.

![InsightEdge Badge](https://img.shields.io/badge/AIV-InsightEdge-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688)
![Python](https://img.shields.io/badge/Python-3.8+-3776AB)

## 🚀 Features

- **Interactive Notebooks**: Create, edit, and save notebook documents with support for both code and markdown cells.
- **Embedded AI Assistant**: A dedicated AI widget to help you write code, explain concepts, or analyze your notebook content.
- **Database Explorer**: Manage multiple database connections (PostgreSQL) and execute SQL queries directly from the notebook.
- **Document Intelligence**: Upload and chat with documents (PDF, DOCX, TXT). The AI processes the content to provide contextual answers.
- **Jupyter Compatibility**: Import existing `.ipynb` files to continue your work in the InsightEdge environment.
- **Session History**: Automatically tracks your AI queries and tool usage for easy reference.

## 🛠️ Getting Started

### Prerequisites

- **Python**: Version 3.8 or higher is recommended.
- **Pip**: Python package manager.

### Installation

1. **Clone or Download** the repository to your local machine.
2. **Navigate** to the project directory:
   ```bash
   cd "AIV Notebook widget"
   ```
3. **Create a Virtual Environment** (Recommended):
   ```bash
   # Windows
   python -m venv venv
   
   # macOS/Linux
   python3 -m venv venv
   ```
4. **Activate the Virtual Environment**:
   ```bash
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```
5. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
6. **Select the Correct Python Interpreter** (Important Step for VS Code users):
   - Inside VS Code, press `Ctrl + Shift + P`.
   - Type and select: `Python: Select Interpreter`.
   - Choose the interpreter that points to your virtual environment (`.\venv\Scripts\python.exe` on Windows).
   - ✅ This ensures that all installed dependencies and project execution use the correct virtual environment.

### Running the Application

To start the InsightEdge AI Notebook server, run the following command from the root directory:

```bash
python -m app.main
```

The application will be accessible at:
👉 **[http://localhost:8090](http://localhost:8090)**

## 🐳 Deployment with Docker

For easy deployment on a server, you can use Docker and Docker Compose.

### Prerequisites
- Docker and Docker Compose installed on your machine/server.

### Steps to Deploy

1. **Navigate** to the project directory.
2. **Run the following command**:
   ```bash
   docker-compose up -d --build
   ```
3. **Verify**: The application will be running on port `8090`.

### Data Persistence
The `docker-compose.yml` is configured to persist your notebooks, connection settings, and history by mounting local files/directories into the container.

## 📂 Project Structure

- `app/`: Core backend logic built with FastAPI.
- `static/`: Frontend assets including HTML, CSS, and interactive JavaScript modules.
- `notebooks/`: Local storage for your saved notebook JSON files.
- `scripts/`: Utility scripts for database checks and verification.
- `requirements.txt`: List of required Python packages.

## ⚙️ Configuration

You can customize the application behavior by creating a `.env` file in the root directory. This can be used to configure database connection defaults or AI model parameters if applicable.

---
